# Data dictionary

All rows are synthetic. Identifiers and shipper names refer to no real company or vehicle. Amounts are Philippine pesos, weights kilograms, road distances kilometres, durations hours, and timestamps ISO 8601 with UTC+08:00. Boolean CSV fields use `True` or `False`.

## Trucks

| Fields | Meaning |
| --- | --- |
| `truck_id`, `equipment`, `location` | Identifier, required `40ft_dry_van` type, current Manila/Calamba hub |
| `release_time` | Earliest empty release after the primary delivery |
| `recovery_base`, `northbound_collection`, `committed_northbound` | CDO/Davao home base, next primary cargo collection, commitment flag |
| `available` | Truck status verified available |
| `pallet_capacity`, `payload_kg`, `volume_m3` | Aggregate capacity limits |
| `max_pallet_length_m`, `max_pallet_width_m`, `max_pallet_height_m` | Individual standard pallet limits; no rotation/3D packing model |
| `tare_front_kg`, `tare_rear_kg` | Empty axle-group weights |
| `front_group_limit_kg`, `rear_group_limit_kg`, `gross_limit_kg` | Fictional planning limits, including tare |
| `driver_hours_remaining` | Initial driving budget; demo requires at least 8 hours |
| `clean_for_food` | Hygiene permission for the food compatibility group |
| `data_verified`, `updated_at` | Source verification and last update; maximum age 12 hours at the fixed clock |

## Shipper loads

| Fields | Meaning |
| --- | --- |
| `load_id`, `shipper` | Unique request ID and dummy shipper name |
| `pickup_hub`, `destination` | Shared consolidation hub and single receiving city |
| `cargo_class` | `dry_grocery`, `retail_goods`, `construction_consumables`, `agricultural_inputs` |
| `compatibility_group` | `food` or `general`; a bundle cannot mix the groups |
| `pallets`, `weight_kg`, `volume_m3` | Total request capacity use |
| `pallet_length_m`, `pallet_width_m`, `pallet_height_m` | Maximum size of a pallet in the request |
| `front_payload_fraction` | Planned fraction of shipment weight on the front group; remainder on rear group |
| `packaging_verified`, `dimensions_verified` | Required cargo acceptance checks |
| `pickup_start`, `pickup_end` | All collection/loading occurs within the intersection of the bundled windows |
| `delivery_start`, `delivery_end` | All unloading occurs within the intersection of the bundled confirmed windows |
| `revenue_php` | Total booked revenue potential for the request |
| `hazardous`, `temperature_controlled`, `high_value`, `crane_required` | Hard exclusion flags |
| `declared_value_php` | Extra demo high-value limit: PHP 1,000,000 |
| `contractual` | Soft priority in the contract-coverage score |
| `priority` | Descriptive 1–3 indicator, retained in candidate output; not independently weighted |
| `crossdock_confirmed`, `receiver_capacity_pallets` | Davao confirmation and maximum pallets per receiving trip |
| `data_verified`, `updated_at` | Source quality and timestamp |

## Ferry departures

| Fields | Meaning |
| --- | --- |
| `sailing_id`, `leg` | Unique departure and `Matnog-Allen` / `Liloan-Surigao` leg |
| `departure`, `arrival`, `cutoff` | Invented schedule; queue must finish by cutoff |
| `available_slots` | Unreserved vehicle spaces collectively available to this pilot's recommendations |
| `cancelled`, `prebookable`, `confirmed_capacity` | Hard service availability and verification flags |
| `weather_risk` | Fictional 0–1 planning risk feature |
| `queue_hours` | Pre-cutoff operational port queue; does not count as driver rest |
| `fare_php` | Vehicle fare and port charge for the leg |
| `data_verified`, `updated_at` | Source quality and timestamp |

Available slots are not booking confirmations. Dispatcher action is still required outside this application.

## Historical trip outcomes

| Fields | Meaning |
| --- | --- |
| `trip_id`, `completed_at` | Historical trip identifier and completion timestamp for chronological splitting |
| `weather_risk`, `queue_hours` | Weather maximum and aggregate queue allowance known at planning |
| `unbooked_crossings` | Number of crossings without a booking at planning; 0–2 in history, 0 for eligible proposed plans |
| `road_km`, `fill_ratio` | Planned road distance and pallet fill ratio |
| `actual_extra_delay_hours` | Training target: realised extra delay beyond the planned nominal journey |
| `actual_variable_cost_php` | Recorded realised cost; provided for future cost calibration, not used by this sample delay model |
| `claim` | Illustrative claims flag; included for future pilot monitoring, not a prediction feature |
| `verified` | Only verified rows enter training, residual calibration or test evaluation |

Historical targets are generated from a synthetic weather, queue, booking and distance relationship plus random noise. They are not reconstructed operational evidence.

## Candidate and audit exports

Candidate IDs identify a particular truck, load set and sailing pair within one run. Use the `run_id` as well as `candidate_id` when retaining decisions. `commercial_exception` flags revenue below the configured threshold. `allocation_eligible` additionally requires the commercial policy, positive incremental gain and positive score. `estimated_service_reliability` is a calibration-residual estimate, not observed on-time performance.

`audit.csv` assigns a source/pilot eligibility flag and an explanation to every truck, shipment and sailing. Eligible shipments can subsequently fail bundle constraints, be held by commercial settings, or lose to competing fleet allocations. `rejection_counts.csv` counts failed attempts, not unique loads.
