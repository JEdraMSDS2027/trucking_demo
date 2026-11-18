# Baseline sample results

These results come from seed 42 at the fixed planning clock of 9 November 2026, 06:00 Philippine time. They are entirely synthetic.

The prototype recommends **4 of 5 eligible trucks**, consolidating **15 shipments**. Two additional trucks fail the initial driver/equipment rules. Of 44 requests, 34 pass the source and pilot filters; bundle feasibility and fleet competition determine which are selected.

| Measure | Sample result |
| --- | ---: |
| Total recommended revenue | PHP 628,079 |
| Average revenue per selected trip | PHP 157,019.75 |
| Selected trips' contribution before ownership | PHP 217,693 |
| Gain compared with empty repositioning | PHP 596,683 |
| Whole eligible fleet contribution, including unmatched empty movement | PHP 116,203 |
| Eligible fleet loaded road kilometres | 76.8% |
| Average selected pallet fill | 98.75% |
| Contractual requests selected | 4 |

| Truck | Receiving hub | Shipments | Pallets | Revenue PHP | Trip contribution PHP |
| --- | --- | ---: | ---: | ---: | ---: |
| TRK-001 | Cagayan de Oro | 3 | 19 | 146,840 | 48,106 |
| TRK-002 | Cagayan de Oro | 4 | 20 | 170,691 | 69,429.60 |
| TRK-004 | Cagayan de Oro | 4 | 20 | 165,927 | 66,507 |
| TRK-005 | Davao | 4 | 20 | 144,621 | 33,650.40 |

The fleet solver found an optimal solution within the generated shared-hub, maximum-four-shipment candidate space under the default weights. This is not a claim of optimality across every possible route, collection address or shipment combination.

The learned delay model uses 868 verified synthetic trips, excludes 32 unverified records, and separates training/calibration/testing chronologically into 520/174/174 rows. On the held-out test set, mean absolute delay error is **2.07 hours**, compared with **4.76 hours** for a mean-delay baseline. The nominal P90 upper bound covers **91.4%** of test delays.

These figures demonstrate implementation mechanics. Actual delivery reliability, safety performance and dispatcher acceptance targets require a real shadow-mode pilot. See `selected.csv` for manifests and sailings, `audit.csv` for request-level explanations, and `summary.json` for the exact settings and solver status.
