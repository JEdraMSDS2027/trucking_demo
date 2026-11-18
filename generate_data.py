"""Reproducible, entirely fictional Philippine backhaul pilot data."""
from pathlib import Path
import argparse
import numpy as np
import pandas as pd

BASE = pd.Timestamp("2026-11-09 06:00", tz="Asia/Manila")


def make_data(seed=42):
    rng = np.random.default_rng(seed)
    stamp = BASE - pd.Timedelta(minutes=30)
    trucks = []
    for i in range(7):
        trucks.append(dict(
            truck_id=f"TRK-{i+1:03}", equipment="40ft_dry_van" if i != 6 else "open_flatbed",
            location="Manila" if i % 2 == 0 else "Calamba",
            release_time=BASE + pd.Timedelta(hours=i * 2),
            recovery_base="Davao" if i in (2, 4) else "Cagayan de Oro",
            northbound_collection=BASE + pd.Timedelta(days=6, hours=i * 2),
            committed_northbound=True, available=True,
            pallet_capacity=20, payload_kg=18000, volume_m3=60,
            max_pallet_length_m=1.2, max_pallet_width_m=1.0, max_pallet_height_m=2.4,
            tare_front_kg=5000, tare_rear_kg=7000,
            front_group_limit_kg=10500, rear_group_limit_kg=20000,
            gross_limit_kg=30000, driver_hours_remaining=3 if i == 5 else 8,
            clean_for_food=(i != 3), data_verified=True, updated_at=stamp,
        ))
    loads = []
    cargo = ["dry_grocery", "retail_goods", "construction_consumables", "agricultural_inputs"]
    for i in range(44):
        dest = "Davao" if i % 3 == 0 else "Cagayan de Oro"
        pallets = int(rng.integers(3, 8))
        kind = cargo[i % 4]
        loads.append(dict(
            load_id=f"LOAD-{i+1:03}", shipper=f"Demo Shipper {i+1:02}",
            pickup_hub="Manila" if i % 4 < 2 else "Calamba", destination=dest,
            cargo_class=kind, compatibility_group="food" if kind == "dry_grocery" else "general",
            pallets=pallets, weight_kg=int(pallets * rng.integers(420, 810)),
            volume_m3=round(pallets * 1.2 * 1.0 * 1.65, 2),
            pallet_length_m=1.2, pallet_width_m=1.0, pallet_height_m=1.65,
            front_payload_fraction=round(float(rng.uniform(.35, .42)), 3),
            packaging_verified=True, dimensions_verified=True,
            pickup_start=BASE + pd.Timedelta(hours=int(rng.integers(0, 12))),
            pickup_end=BASE + pd.Timedelta(hours=34),
            delivery_start=BASE + pd.Timedelta(days=3),
            delivery_end=BASE + pd.Timedelta(days=5, hours=18 if dest == "Davao" else 8),
            revenue_php=int(pallets * rng.integers(6500, 9500)),
            hazardous=False, temperature_controlled=False, high_value=False, crane_required=False,
            declared_value_php=int(rng.integers(100000, 650000)),
            contractual=(i % 5 == 0), priority=int(rng.integers(1, 4)),
            crossdock_confirmed=True, receiver_capacity_pallets=24,
            data_verified=True, updated_at=stamp,
        ))
    # Deliberate cases for the rejection audit and classroom demonstration.
    changes = {
        0: {"hazardous": True}, 1: {"temperature_controlled": True},
        2: {"high_value": True, "declared_value_php": 2500000},
        3: {"crane_required": True}, 4: {"data_verified": False},
        5: {"updated_at": BASE - pd.Timedelta(hours=30)},
        6: {"pallet_height_m": 3.2}, 7: {"weight_kg": 24000},
        8: {"delivery_end": BASE + pd.Timedelta(hours=30)},
        9: {"pickup_end": BASE - pd.Timedelta(hours=1)},
        10: {"crossdock_confirmed": False, "destination": "Davao"},
        11: {"packaging_verified": False},
    }
    for idx, values in changes.items():
        loads[idx].update(values)

    sailings = []
    for leg, first, duration, fare in [("Matnog-Allen", 36, 2, 15500),
                                        ("Liloan-Surigao", 72, 4, 16000)]:
        for j in range(12):
            departure = BASE + pd.Timedelta(hours=first + 12 * j)
            sailings.append(dict(
                sailing_id=("MA" if leg == "Matnog-Allen" else "LS") + f"-{j+1:02}",
                leg=leg, departure=departure,
                arrival=departure + pd.Timedelta(hours=duration),
                cutoff=departure - pd.Timedelta(hours=1.5),
                available_slots=2 if j % 3 == 0 else 3,
                cancelled=False, prebookable=True, confirmed_capacity=True,
                weather_risk=round(float(rng.uniform(.08, .38)), 2),
                queue_hours=round(float(rng.uniform(1, 3)), 1), fare_php=fare,
                data_verified=True, updated_at=stamp,
            ))
    # Past synthetic trips have only features that could have been known at planning.
    history = []
    for i in range(900):
        weather = float(rng.uniform(0, 1))
        queues = float(rng.uniform(1, 12))
        unbooked = int(rng.integers(0, 3))
        km = int(rng.choice([1500, 1790]))
        fill = float(rng.uniform(.15, 1))
        delay = max(0, 1.8 + 15 * weather**2 + .6 * queues + 2.7 * unbooked
                    + .002 * (km - 1500) + 1.1 * fill + rng.normal(0, 2.7))
        history.append(dict(
            trip_id=f"HIST-{i+1:04}", completed_at=BASE - pd.Timedelta(days=300 - i / 3.1),
            weather_risk=round(weather, 3), queue_hours=round(queues, 2),
            unbooked_crossings=unbooked, road_km=km, fill_ratio=round(fill, 3),
            actual_extra_delay_hours=round(delay, 2),
            actual_variable_cost_php=round(31 * km + 31500 + 16500 + 5500 * fill + delay * 200),
            claim=(rng.random() < .015), verified=(i % 29 != 0),
        ))
    return {"trucks": pd.DataFrame(trucks), "loads": pd.DataFrame(loads),
            "sailings": pd.DataFrame(sailings), "history": pd.DataFrame(history)}


def write_data(folder, seed=42):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for name, frame in make_data(seed).items():
        frame.to_csv(folder / f"{name}.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data")
    args = parser.parse_args()
    write_data(args.output, args.seed)
    print(f"Wrote four synthetic datasets to {args.output}")
