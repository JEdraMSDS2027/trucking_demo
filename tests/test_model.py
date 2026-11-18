from collections import Counter
from dataclasses import replace
import sys
from pathlib import Path
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from generate_data import BASE, make_data
from model import Settings, allocate, capacity_reason, filter_inputs, run_model, train_delay_model


@pytest.fixture(scope="module")
def data():
    return make_data(42)


@pytest.fixture(scope="module")
def result(data):
    return run_model(data)


def test_seed_reproduces_inputs(data):
    for key, value in make_data(42).items():
        pd.testing.assert_frame_equal(data[key], value)


def test_hard_cargo_exclusions_and_staleness(data):
    trucks, loads, sailings, audit = filter_inputs(data, BASE, Settings())
    assert len(trucks) == 5
    assert not set(["LOAD-001", "LOAD-002", "LOAD-003", "LOAD-004", "LOAD-005", "LOAD-006", "LOAD-010", "LOAD-011", "LOAD-012"]) & set(loads.load_id)
    assert len(sailings) == 24
    assert audit.loc[audit.id.eq("TRK-006"), "reason"].str.contains("driver").all()


def test_no_double_booking_and_ferry_slots(result):
    selected = result["selected"]
    assert len(selected) > 0
    ids = [lid for group in selected.load_ids for lid in group]
    assert len(ids) == len(set(ids))
    assert selected.truck_id.is_unique
    slots = result["sailings"].set_index("sailing_id").available_slots.to_dict()
    usage = Counter(selected.sailing_1.tolist() + selected.sailing_2.tolist())
    assert all(used <= slots[sid] for sid, used in usage.items())


def test_all_recommendations_satisfy_physical_and_timing_rules(result):
    trucks = result["trucks"].set_index("truck_id")
    loads = result["loads"]
    for _, plan in result["selected"].iterrows():
        manifest = loads.loc[loads.load_id.isin(plan.load_ids)]
        assert capacity_reason(trucks.loc[plan.truck_id], manifest) is None
        assert plan.delivery_end <= manifest.delivery_end.min()
        assert plan.pickup_time >= manifest.pickup_start.max()
        assert plan.recovery_slack_hours >= Settings().recovery_buffer_hours
        assert plan.revenue_php >= Settings().minimum_revenue
        assert plan.destination == trucks.loc[plan.truck_id].recovery_base
        for event in plan.timeline:
            assert event["end"] >= event["start"]
            if event["activity"].startswith(("Road", "Allen", "Surigao")):
                assert (event["end"] - event["start"]).total_seconds()/3600 <= 8 + 1e-6


def test_known_impossible_loads_never_selected(result):
    ids = {lid for group in result["selected"].load_ids for lid in group}
    assert not {f"LOAD-{i:03}" for i in range(1, 13)} & ids


def test_axle_limit_and_food_segregation_are_hard(data):
    truck = data["trucks"].iloc[0].copy()
    bundle = data["loads"].iloc[[20, 24]].copy()
    bundle["weight_kg"] = 4000
    bundle["front_payload_fraction"] = .9
    assert capacity_reason(truck, bundle) == "Gross or planned axle-group load"
    bundle["front_payload_fraction"] = .35
    bundle.iloc[1, bundle.columns.get_loc("compatibility_group")] = "general"
    assert capacity_reason(truck, bundle) == "Food and general cargo segregation"


def test_stale_data_returns_empty_result(data):
    changed = {key: value.copy() for key, value in data.items()}
    for name in ["trucks", "loads", "sailings"]:
        changed[name]["updated_at"] = BASE - pd.Timedelta(days=1)
    result = run_model(changed)
    assert result["selected"].empty
    assert result["metrics"]["eligible_trucks"] == 0
    assert result["metrics"]["revenue_php"] == 0


def test_allocator_can_use_alternative_sailing_to_resolve_conflict():
    candidates = pd.DataFrame([
        dict(candidate_id="A", truck_id="T1", load_ids=("L1",), sailing_1="F1", sailing_2="G1", score=100, allocation_eligible=True),
        dict(candidate_id="B", truck_id="T2", load_ids=("L2",), sailing_1="F1", sailing_2="G1", score=99, allocation_eligible=True),
        dict(candidate_id="C", truck_id="T2", load_ids=("L2",), sailing_1="F2", sailing_2="G2", score=90, allocation_eligible=True),
    ])
    sailings = pd.DataFrame(dict(sailing_id=["F1", "G1", "F2", "G2"], available_slots=[1, 1, 1, 1]))
    selected, status = allocate(candidates, sailings)
    assert set(selected.candidate_id) == {"A", "C"}
    assert status["optimal"]


def test_ml_excludes_unverified_history(data):
    original = train_delay_model(data["history"])
    mutated = data["history"].copy()
    mutated.loc[~mutated.verified, "actual_extra_delay_hours"] = 999999
    comparison = train_delay_model(mutated)
    assert original["metrics"] == comparison["metrics"]
    assert original["metrics"]["mae_hours"] < original["metrics"]["baseline_mae_hours"]


def test_fleet_cost_reconciliation(result):
    m = result["metrics"]
    assert m["fleet_contribution_php"] == pytest.approx(-m["empty_baseline_cost_php"] + m["incremental_gain_php"])
    selected = result["selected"]
    assert (selected.revenue_php - selected.variable_cost_php).sum() == pytest.approx(m["selected_trip_contribution_php"])


def test_revenue_threshold_and_exception_switch(data, result):
    from model import score_candidates
    settings = replace(Settings(), minimum_revenue=1000000)
    strict = score_candidates(result["candidates"], result["learned"], settings)
    assert not strict.allocation_eligible.any()
    exceptions = score_candidates(result["candidates"], result["learned"], replace(settings, allow_revenue_exceptions=True))
    assert exceptions.commercial_exception.all()
    assert exceptions.allocation_eligible.any()
