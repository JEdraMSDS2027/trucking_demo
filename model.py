"""Rules + learned delay estimates + binary fleet allocation. No booking actions."""
from collections import Counter
from dataclasses import dataclass, asdict
from itertools import combinations
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error

FEATURES = ["weather_risk", "queue_hours", "unbooked_crossings", "road_km", "fill_ratio"]
DATE_COLUMNS = {
    "trucks": ["release_time", "northbound_collection", "updated_at"],
    "loads": ["pickup_start", "pickup_end", "delivery_start", "delivery_end", "updated_at"],
    "sailings": ["departure", "arrival", "cutoff", "updated_at"],
    "history": ["completed_at"],
}


@dataclass(frozen=True)
class Settings:
    minimum_revenue: int = 110000
    allow_revenue_exceptions: bool = False
    weather_shock: float = 0
    delay_buffer_hours: float = 6
    stale_hours: float = 12
    max_bundle: int = 4
    enable_davao: bool = True
    road_cost_per_km: float = 31
    contribution_weight: float = .6
    reliability_weight: float = .2
    coverage_weight: float = .1
    loaded_km_weight: float = .1
    max_daily_drive: float = 8
    rest_hours: float = 10
    recovery_buffer_hours: float = 12


def load_data(folder):
    result = {}
    for name, dates in DATE_COLUMNS.items():
        frame = pd.read_csv(Path(folder) / f"{name}.csv")
        for col in dates:
            frame[col] = pd.to_datetime(frame[col], utc=True, format="mixed").dt.tz_convert("Asia/Manila")
        result[name] = frame
    return result


def fingerprint(data, settings):
    digest = hashlib.sha256(json.dumps(asdict(settings), sort_keys=True).encode())
    for name in sorted(data):
        digest.update(data[name].to_csv(index=False).encode())
    return digest.hexdigest()[:16]


def train_delay_model(history):
    clean = history.loc[history.verified.eq(True)].sort_values("completed_at")
    if len(clean) < 100:
        raise ValueError("At least 100 verified historical trips are required.")
    # Three chronological blocks: training, residual calibration, untouched testing.
    i, j = int(.60 * len(clean)), int(.80 * len(clean))
    train, calibration, test = clean.iloc[:i], clean.iloc[i:j], clean.iloc[j:]
    model = RandomForestRegressor(n_estimators=100, max_depth=8, min_samples_leaf=6,
                                  random_state=42, n_jobs=1)
    model.fit(train[FEATURES], train.actual_extra_delay_hours)
    residuals = calibration.actual_extra_delay_hours.to_numpy() - model.predict(calibration[FEATURES])
    prediction = model.predict(test[FEATURES])
    baseline = np.repeat(train.actual_extra_delay_hours.mean(), len(test))
    q90 = float(np.quantile(residuals, .90))
    metrics = dict(verified_rows=len(clean), excluded_unverified=len(history) - len(clean),
                   train_rows=len(train), calibration_rows=len(calibration), test_rows=len(test),
                   mae_hours=float(mean_absolute_error(test.actual_extra_delay_hours, prediction)),
                   baseline_mae_hours=float(mean_absolute_error(test.actual_extra_delay_hours, baseline)),
                   p90_test_coverage=float(np.mean(test.actual_extra_delay_hours <= prediction + q90)),
                   residual_p90_hours=q90)
    test_output = test[["trip_id", "completed_at", "actual_extra_delay_hours"]].copy()
    test_output["predicted_delay_hours"] = prediction
    return dict(model=model, residuals=residuals, metrics=metrics, test_predictions=test_output,
                importance=pd.DataFrame({"feature": FEATURES, "importance": model.feature_importances_}))


def is_current(row, now, settings):
    age = (now - row.updated_at).total_seconds() / 3600
    return bool(row.data_verified) and 0 <= age <= settings.stale_hours


def filter_inputs(data, now, settings):
    audits, valid_loads, valid_trucks, valid_sailings = [], [], [], []
    for kind in ["loads", "trucks", "sailings"]:
        key = {"loads": "load_id", "trucks": "truck_id", "sailings": "sailing_id"}[kind]
        for _, row in data[kind].iterrows():
            reasons = []
            if not is_current(row, now, settings):
                reasons.append("Unverified, stale or future-dated source data")
            if kind == "loads":
                for flag, label in [("hazardous", "Hazardous cargo excluded"),
                                    ("temperature_controlled", "Temperature-controlled cargo excluded"),
                                    ("high_value", "Very high-value cargo excluded"),
                                    ("crane_required", "Crane handling excluded")]:
                    if bool(row[flag]):
                        reasons.append(label)
                if row.declared_value_php > 1000000 and not row.high_value:
                    reasons.append("Declared value exceeds fictional PHP 1m pilot limit")
                if not row.packaging_verified or not row.dimensions_verified:
                    reasons.append("Packaging or dimensions not verified")
                if row.cargo_class not in {"dry_grocery", "retail_goods", "construction_consumables", "agricultural_inputs"}:
                    reasons.append("Cargo class outside pilot")
                if row.pickup_hub not in {"Manila", "Calamba"}:
                    reasons.append("Pickup hub outside pilot")
                if row.destination not in {"Cagayan de Oro", "Davao"}:
                    reasons.append("Destination outside pilot")
                if row.destination == "Davao" and (not settings.enable_davao or not row.crossdock_confirmed):
                    reasons.append("Davao branch disabled or cross-dock unconfirmed")
                if row.pickup_end < now or row.pickup_end < row.pickup_start:
                    reasons.append("Pickup window expired or invalid")
                if row.delivery_end < row.delivery_start:
                    reasons.append("Invalid delivery window")
                if (row.pallets <= 0 or row.weight_kg <= 0 or row.volume_m3 <= 0 or row.revenue_php < 0
                    or not 0 <= row.front_payload_fraction <= 1):
                    reasons.append("Invalid physical or commercial values")
                if not reasons:
                    valid_loads.append(row)
            elif kind == "trucks":
                if row.equipment != "40ft_dry_van" or not row.available:
                    reasons.append("Equipment or availability outside dry-van pilot")
                if row.driver_hours_remaining < settings.max_daily_drive:
                    reasons.append("Insufficient initial driver hours; dispatch must rest or replace driver")
                if not row.committed_northbound:
                    reasons.append("No committed northbound recovery load")
                if not reasons:
                    valid_trucks.append(row)
            else:
                if row.cancelled or row.available_slots <= 0:
                    reasons.append("Cancelled sailing or no vehicle capacity")
                if not row.prebookable or not row.confirmed_capacity:
                    reasons.append("Prebooking or capacity not verified")
                if row.departure <= row.cutoff or row.arrival <= row.departure:
                    reasons.append("Invalid sailing sequence")
                if not reasons:
                    valid_sailings.append(row)
            audits.append(dict(entity=kind, id=row[key], eligible=not reasons,
                               reason="; ".join(reasons) if reasons else "Passed source and pilot rules"))
    return (pd.DataFrame(valid_trucks, columns=data["trucks"].columns),
            pd.DataFrame(valid_loads, columns=data["loads"].columns),
            pd.DataFrame(valid_sailings, columns=data["sailings"].columns), pd.DataFrame(audits))


def drive(start, hours, budget, settings, label):
    """Explicit single-driver blocks; policy limits are fictional, not legal certification."""
    events, remaining = [], hours
    while remaining > 1e-8:
        if budget < 1e-8:
            end = start + pd.Timedelta(hours=settings.rest_hours)
            events.append(dict(activity="Driver rest", start=start, end=end))
            start, budget = end, settings.max_daily_drive
        block = min(remaining, budget)
        end = start + pd.Timedelta(hours=block)
        events.append(dict(activity=label, start=start, end=end))
        start, budget, remaining = end, budget - block, remaining - block
    return start, budget, events


def prepare_bundle(bundle):
    return SimpleNamespace(
        pickup_hub=bundle.iloc[0].pickup_hub, destination=bundle.iloc[0].destination,
        shipment_count=len(bundle), load_ids=tuple(bundle.load_id),
        pickup_start=bundle.pickup_start.max(), pickup_end=bundle.pickup_end.min(),
        delivery_start=bundle.delivery_start.max(), delivery_end=bundle.delivery_end.min(),
        pallets=bundle.pallets.sum(), weight_kg=bundle.weight_kg.sum(), volume_m3=bundle.volume_m3.sum(),
        revenue_php=bundle.revenue_php.sum(), contractual_loads=bundle.contractual.sum(),
        priority_points=bundle.priority.sum(),
        pallet_length_m=bundle.pallet_length_m.max(), pallet_width_m=bundle.pallet_width_m.max(),
        pallet_height_m=bundle.pallet_height_m.max(),
        front_kg=(bundle.weight_kg * bundle.front_payload_fraction).sum(),
        rear_kg=(bundle.weight_kg * (1-bundle.front_payload_fraction)).sum(),
        compatibility_count=bundle.compatibility_group.nunique(),
        food="food" in bundle.compatibility_group.values,
        receiver_capacity_pallets=bundle.receiver_capacity_pallets.min())


def capacity_reason(truck, bundle):
    if isinstance(bundle, pd.DataFrame):
        bundle = prepare_bundle(bundle)
    if bundle.pallets > truck.pallet_capacity:
        return "Pallet capacity"
    weight = bundle.weight_kg
    if weight > truck.payload_kg or bundle.volume_m3 > truck.volume_m3:
        return "Payload or volume capacity"
    if (bundle.pallet_length_m > truck.max_pallet_length_m
        or bundle.pallet_width_m > truck.max_pallet_width_m
        or bundle.pallet_height_m > truck.max_pallet_height_m):
        return "Pallet dimensions"
    front = truck.tare_front_kg + bundle.front_kg
    rear = truck.tare_rear_kg + bundle.rear_kg
    if front > truck.front_group_limit_kg or rear > truck.rear_group_limit_kg or front + rear > truck.gross_limit_kg:
        return "Gross or planned axle-group load"
    if bundle.compatibility_count > 1:
        return "Food and general cargo segregation"
    if bundle.food and not truck.clean_for_food:
        return "Food hygiene status"
    if bundle.pallets > bundle.receiver_capacity_pallets:
        return "Receiver or cross-dock capacity"
    return None


def route_timing(truck, bundle, first, second, settings):
    hub, dest = bundle.pickup_hub, bundle.destination
    # Only shared-hub pickups and a single receiving hub per bundle are modelled.
    deadhead_km = 0 if hub == truck.location else 55
    travel_to_hub = deadhead_km / 40
    start = max(truck.release_time + pd.Timedelta(hours=travel_to_hub), bundle.pickup_start)
    finish = start + pd.Timedelta(hours=1.5 + .35 * bundle.shipment_count)
    if finish > bundle.pickup_end:
        return None, "Pickup window"
    events = []
    if travel_to_hub:
        events.append(dict(activity="Road to consolidation hub", start=truck.release_time,
                           end=truck.release_time + pd.Timedelta(hours=travel_to_hub)))
    events.append(dict(activity=f"Consolidate at {hub}", start=start, end=finish))
    # Include deadhead driving in the same initial driver budget.
    budget = truck.driver_hours_remaining - travel_to_hub
    t, budget, driving = drive(finish, 14, budget, settings, "Road to Matnog")
    events.extend(driving)
    guard = settings.delay_buffer_hours / 2 + settings.weather_shock * 10
    for sailing, road_hours, label in [(first, 12, "Allen to Liloan"),
                                        (second, 6 if dest == "Cagayan de Oro" else 11, f"Surigao to {dest}")]:
        port_ready = t + pd.Timedelta(hours=sailing.queue_hours)
        if port_ready > sailing.cutoff:
            return None, "Ferry cutoff or connection"
        events.append(dict(activity=f"Queue and cutoff {sailing.sailing_id}", start=t, end=port_ready))
        if (sailing.departure - port_ready).total_seconds() / 3600 >= settings.rest_hours:
            budget = settings.max_daily_drive
        events.append(dict(activity=f"Wait {sailing.sailing_id}", start=port_ready, end=sailing.departure))
        events.append(dict(activity=f"Ferry {sailing.leg}", start=sailing.departure, end=sailing.arrival))
        t = sailing.arrival + pd.Timedelta(hours=guard)
        events.append(dict(activity="Planning delay buffer", start=sailing.arrival, end=t))
        t, budget, driving = drive(t, road_hours, budget, settings, label)
        events.extend(driving)
    physical_arrival = t
    delivery_start = max(t, bundle.delivery_start)
    delivery_end = delivery_start + pd.Timedelta(hours=1 + .25 * bundle.shipment_count)
    if delivery_end > bundle.delivery_end:
        return None, "Delivery appointment"
    if delivery_end + pd.Timedelta(hours=settings.recovery_buffer_hours) > truck.northbound_collection:
        return None, "Northbound recovery buffer"
    if delivery_start > physical_arrival:
        events.append(dict(activity="Wait for receiver window", start=physical_arrival, end=delivery_start))
    events.append(dict(activity="Delivery and unloading", start=delivery_start, end=delivery_end))
    return dict(pickup_time=start, guarded_arrival=physical_arrival, delivery_start=delivery_start,
                delivery_end=delivery_end, timeline=events), None


def route_plan(truck, bundle, first, second, settings, timing_cache):
    hub, dest = bundle.pickup_hub, bundle.destination
    key = (truck.truck_id, hub, dest, bundle.shipment_count,
           bundle.pickup_start, bundle.pickup_end, bundle.delivery_start, bundle.delivery_end,
           first.sailing_id, second.sailing_id)
    if key not in timing_cache:
        timing_cache[key] = route_timing(truck, bundle, first, second, settings)
    timing, reason = timing_cache[key]
    if reason:
        return None, reason
    start, physical_arrival = timing["pickup_time"], timing["guarded_arrival"]
    delivery_start, delivery_end = timing["delivery_start"], timing["delivery_end"]
    events = timing["timeline"]
    deadhead_km = 0 if hub == truck.location else 55
    road_km = (1500 if dest == "Cagayan de Oro" else 1790) + deadhead_km
    revenue = float(bundle.revenue_php)
    fill = bundle.pallets / truck.pallet_capacity
    road_cost = road_km * settings.road_cost_per_km * (1 + .08 * fill)
    ferry_cost = first.fare_php + second.fare_php
    other_cost = 14500 + 500 * bundle.shipment_count + 200 * settings.delay_buffer_hours + settings.weather_shock * 4000
    total_cost = road_cost + ferry_cost + other_cost
    empty_km = 1500 if truck.recovery_base == "Cagayan de Oro" else 1790
    baseline_cost = empty_km * settings.road_cost_per_km + 31500 + 14500
    guarded_slack = min((bundle.delivery_end - delivery_end).total_seconds() / 3600,
                        (truck.northbound_collection - pd.Timedelta(hours=settings.recovery_buffer_hours) - delivery_end).total_seconds() / 3600)
    return dict(
        truck_id=truck.truck_id, load_ids=tuple(bundle.load_ids), pickup_hub=hub, destination=dest,
        sailing_1=first.sailing_id, sailing_2=second.sailing_id, pickup_time=start,
        guarded_arrival=physical_arrival, delivery_start=delivery_start, delivery_end=delivery_end,
        latest_delivery=bundle.delivery_end, northbound_collection=truck.northbound_collection,
        recovery_slack_hours=(truck.northbound_collection - delivery_end).total_seconds() / 3600,
        schedule_slack_hours=guarded_slack, pallets=int(bundle.pallets),
        weight_kg=float(bundle.weight_kg), fill_ratio=float(fill),
        revenue_php=revenue, road_cost_php=road_cost, ferry_cost_php=float(ferry_cost),
        other_cost_php=other_cost, variable_cost_php=total_cost,
        contribution_php=revenue - total_cost, empty_baseline_cost_php=baseline_cost,
        incremental_gain_php=revenue - (total_cost - baseline_cost),
        road_km=road_km, loaded_km=road_km - deadhead_km, deadhead_km=deadhead_km,
        loaded_km_ratio=(road_km-deadhead_km)/road_km,
        contractual_loads=int(bundle.contractual_loads), priority_points=int(bundle.priority_points),
        weather_risk=min(1., max(first.weather_risk, second.weather_risk) + settings.weather_shock),
        queue_hours=float(first.queue_hours + second.queue_hours), unbooked_crossings=0,
        commercial_exception=revenue < settings.minimum_revenue,
        timeline=events,
    ), None


def generate_candidates(trucks, loads, sailings, settings):
    candidates, counts, load_failures = [], Counter(), {x: Counter() for x in loads.load_id}
    timing_cache = {}
    first_sailings = list(sailings.loc[sailings.leg.eq("Matnog-Allen")].sort_values("departure").itertuples(index=False))
    second_sailings = list(sailings.loc[sailings.leg.eq("Liloan-Surigao")].sort_values("departure").itertuples(index=False))
    groups = []
    for group_key, group in loads.groupby(["pickup_hub", "destination", "compatibility_group"]):
        bundles = []
        for size in range(1, min(settings.max_bundle, len(group)) + 1):
            for indices in combinations(group.index, size):
                bundles.append(prepare_bundle(group.loc[list(indices)]))
        groups.append((group_key, bundles))
    for truck in trucks.itertuples(index=False):
        for (hub, dest, _), bundles in groups:
            if dest != truck.recovery_base:
                continue
            for summary in bundles:
                reason = capacity_reason(truck, summary)
                if reason:
                    counts[reason] += 1
                    for lid in summary.load_ids:
                        load_failures[lid][reason] += 1
                    continue
                # Retain every feasible sailing pair, so fleet optimisation can resolve slot competition.
                for first in first_sailings:
                    if first.departure < truck.release_time or first.departure > summary.delivery_end:
                        continue
                    for second in second_sailings:
                        if second.departure <= first.arrival or second.departure > summary.delivery_end:
                            continue
                        plan, reason = route_plan(truck, summary, first, second, settings, timing_cache)
                        if reason:
                            counts[reason] += 1
                            for lid in summary.load_ids:
                                load_failures[lid][reason] += 1
                        else:
                            candidates.append(plan)
    frame = pd.DataFrame(candidates)
    if not frame.empty:
        frame.insert(0, "candidate_id", [f"PLAN-{i+1:05}" for i in range(len(frame))])
    return frame, counts, load_failures


def score_candidates(candidates, learned, settings):
    if candidates.empty:
        return candidates
    frame = candidates.copy()
    frame["commercial_exception"] = frame.revenue_php.lt(settings.minimum_revenue)
    prediction = learned["model"].predict(frame[FEATURES])
    # Residual CDF is an empirical estimate, not a certified probability.
    available_delay = frame.schedule_slack_hours.to_numpy() + settings.delay_buffer_hours + settings.weather_shock * 20
    residuals = learned["residuals"]
    reliability = np.array([np.mean(residuals <= slack - pred) for slack, pred in zip(available_delay, prediction)])
    frame["predicted_delay_hours"] = prediction
    frame["estimated_service_reliability"] = reliability
    # Guarded timing remains a hard rule; learned risk only changes the score.
    frame["contribution_component"] = frame.contribution_php / 100000
    frame["reliability_component"] = reliability
    frame["coverage_component"] = (frame.contractual_loads / settings.max_bundle).clip(0, 1)
    frame["loaded_km_component"] = frame.loaded_km_ratio
    frame["score"] = 100 * (
        settings.contribution_weight * frame.contribution_component
        + settings.reliability_weight * frame.reliability_component
        + settings.coverage_weight * frame.coverage_component
        + settings.loaded_km_weight * frame.loaded_km_component)
    frame["commercial_eligible"] = (~frame.commercial_exception | settings.allow_revenue_exceptions)
    # An empty move is always available; do not select a value-destroying backhaul.
    frame["allocation_eligible"] = frame.commercial_eligible & frame.incremental_gain_php.gt(0) & frame.score.gt(0)
    return frame.sort_values(["score", "contribution_php"], ascending=False).reset_index(drop=True)


def allocate(candidates, sailings):
    if candidates.empty or not candidates.allocation_eligible.any():
        return candidates.iloc[:0].copy(), dict(status="No allocatable plans", optimal=True, gap=0.)
    frame = candidates.loc[candidates.allocation_eligible].reset_index(drop=True)
    keys = sorted({("truck", t) for t in frame.truck_id}
                  | {("load", l) for ids in frame.load_ids for l in ids}
                  | {("ferry", s) for s in frame.sailing_1}
                  | {("ferry", s) for s in frame.sailing_2})
    lookup = {key: i for i, key in enumerate(keys)}
    matrix = lil_matrix((len(keys), len(frame)), dtype=float)
    upper = np.ones(len(keys))
    slots = sailings.set_index("sailing_id").available_slots.to_dict()
    for i, (kind, key) in enumerate(keys):
        if kind == "ferry":
            upper[i] = slots[key]
    for j, row in frame.iterrows():
        for key in [("truck", row.truck_id), *[("load", l) for l in row.load_ids],
                    ("ferry", row.sailing_1), ("ferry", row.sailing_2)]:
            matrix[lookup[key], j] = 1
    solution = milp(-frame.score.to_numpy(), integrality=np.ones(len(frame)),
                    bounds=Bounds(0, 1), constraints=LinearConstraint(matrix.tocsc(), 0, upper),
                    options={"time_limit": 20., "mip_rel_gap": .001})
    if solution.x is None:
        return frame.iloc[:0], dict(status=str(solution.message), optimal=False, gap=None)
    chosen = frame.loc[solution.x > .5].copy().sort_values("truck_id")
    # Independently validate discrete resource constraints after solving.
    ids = [lid for group in chosen.load_ids for lid in group]
    assert len(ids) == len(set(ids)) and chosen.truck_id.is_unique
    used = Counter(chosen.sailing_1.tolist() + chosen.sailing_2.tolist())
    assert all(count <= slots[sid] for sid, count in used.items())
    return chosen, dict(status=str(solution.message), optimal=solution.status == 0,
                        gap=float(solution.mip_gap) if solution.mip_gap is not None else None)


def run_model(data, settings=Settings(), now=None, learned=None):
    if now is None:
        now = pd.Timestamp("2026-11-09 06:00", tz="Asia/Manila")
    learned = learned or train_delay_model(data["history"])
    trucks, loads, sailings, audit = filter_inputs(data, now, settings)
    candidates, counts, failures = generate_candidates(trucks, loads, sailings, settings)
    candidates = score_candidates(candidates, learned, settings)
    selected, solver = allocate(candidates, sailings)
    selected_ids = {l for ids in selected.get("load_ids", []) for l in ids}
    feasible_ids = {l for ids in candidates.get("load_ids", []) for l in ids}
    allocatable_ids = ({l for ids in candidates.loc[candidates.allocation_eligible, "load_ids"] for l in ids}
                       if not candidates.empty else set())
    for i, row in audit.loc[audit.entity.eq("loads") & audit.eligible].iterrows():
        lid = row.id
        if lid in selected_ids:
            reason = "Selected in fleet recommendation"
        elif lid in allocatable_ids:
            reason = "Feasible; displaced by competing truck, load or ferry allocation"
        elif lid in feasible_ids:
            reason = "Feasible; held by revenue, contribution or score policy"
        else:
            causes = failures.get(lid, Counter())
            reason = "No feasible bundle: " + ", ".join(k for k, _ in causes.most_common(3)) if causes else "No matching destination or eligible truck"
        audit.loc[i, "reason"] = reason
    fleet_km = sum(1500 if t.recovery_base == "Cagayan de Oro" else 1790 for _, t in trucks.iterrows())
    baseline_cost = sum((1500 if t.recovery_base == "Cagayan de Oro" else 1790)
                        * settings.road_cost_per_km + 31500 + 14500 for _, t in trucks.iterrows())
    revenue = float(selected.revenue_php.sum()) if not selected.empty else 0.
    gain = float(selected.incremental_gain_php.sum()) if not selected.empty else 0.
    loaded_km = float(selected.loaded_km.sum()) if not selected.empty else 0.
    detour_km = float(selected.deadhead_km.sum()) if not selected.empty else 0.
    metrics = dict(recommended_trucks=len(selected), eligible_trucks=len(trucks), matched_loads=len(selected_ids),
                   eligible_loads=len(loads), revenue_php=revenue,
                   selected_trip_contribution_php=float(selected.contribution_php.sum()) if not selected.empty else 0.,
                   empty_baseline_cost_php=float(baseline_cost), incremental_gain_php=gain,
                   fleet_contribution_php=-float(baseline_cost) + gain,
                   fleet_loaded_km_ratio=loaded_km / (fleet_km + detour_km) if fleet_km else 0.,
                   average_revenue_php=revenue / len(selected) if len(selected) else 0.,
                   average_fill_ratio=float(selected.fill_ratio.mean()) if len(selected) else 0.,
                   selected_contractual_loads=int(selected.contractual_loads.sum()) if len(selected) else 0)
    return dict(settings=asdict(settings), run_id=fingerprint(data, settings), now=now,
                candidates=candidates, selected=selected, audit=audit,
                rejection_counts=pd.DataFrame(counts.most_common(), columns=["constraint", "attempts"]),
                trucks=trucks, loads=loads, sailings=sailings, learned=learned, metrics=metrics, solver=solver)


def export_run(result, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ["selected", "candidates", "audit", "rejection_counts"]:
        frame = result[name].copy()
        if "timeline" in frame:
            frame = frame.drop(columns="timeline")
        if "load_ids" in frame:
            frame["load_ids"] = frame.load_ids.apply(lambda ids: " | ".join(ids))
        frame.to_csv(folder / f"{name}.csv", index=False)
    report = {key: result[key] for key in ["run_id", "settings", "metrics", "solver"]}
    report["delay_model"] = result["learned"]["metrics"]
    (folder / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    root = Path(__file__).parent
    result = run_model(load_data(root / "data"))
    export_run(result, root / "sample_results")
    print(json.dumps({"metrics": result["metrics"], "solver": result["solver"],
                      "model": result["learned"]["metrics"]}, indent=2))
