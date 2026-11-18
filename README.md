# Philippine Island Trucking Streamlit Demo

A runnable sample model for the supplied **Philippines Island Trucking Case Study**. It combines synthetic data, hard feasibility checks, a learned transit-delay model, and fleet allocation. Every result is a planning recommendation for a dispatcher to review.

All operational records, schedules, costs, equipment limits and model outcomes are fictional. The original case document is not copied into this package.

## Open the demo

On the computer where this package was created, open PowerShell in this folder and run:

```powershell
.\start_demo.ps1
```

Visit **http://127.0.0.1:8501**. Keep the terminal running; press Ctrl+C to stop. The launcher reuses the environment prepared in this workspace. On another computer, it creates a local environment and installs the dependencies. Python 3.11 or newer and internet access are needed for the first installation.

For a standard installation on Windows, macOS or Linux:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

`requirements-lock.txt` records the versions used to verify this delivery. Use it instead of `requirements.txt` to reproduce that environment on compatible Python 3.12 systems.

## Suggested five minute walkthrough

1. Run **Baseline pilot**. Review the recommended trucks, combined loads and revenue. Select **Download this run** to export every feasible candidate, the selected plans, audit and settings.
2. Open **Trip detail & review**. Choose a plan and inspect the manifest, both ferry legs, driver rest blocks, guarded delivery time and next northbound collection.
3. Open **Rejected & unmatched**. Find the intentional hazardous, temperature-controlled, high-value, crane-handled, stale, oversized and late requests. Distinguish a rejected request from a feasible request displaced by a better fleet combination.
4. Change **Scenario** to **First crossing cancelled** or **Ferry capacity squeeze**, then click **Run matching model**. Compare sailings and allocations. Increase weather disruption or the delay buffer to make the timing assumptions more conservative.
5. Try **Stale source records**. The model refuses to recommend movements using outdated operational inputs.
6. Return to the baseline and record a demo dispatcher decision. Approval requires the review checkbox; a below-threshold exception, modification or rejection needs a reason. Download the decision log to retain it.

The demo clock is fixed at **9 November 2026, 06:00 Philippine time** so the same files reproduce the same planning problem. It is deliberately independent of the computer's current date.

## Included files

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit dashboard, scenario controls, trip explanation and session decision log |
| `model.py` | Source checks, bundling, timing, costing, delay learning, ranking and mixed-integer allocation |
| `generate_data.py` | Seeded data generator; seed 42 is the bundled example |
| `data/trucks.csv` | 7 returning trucks with release times, capacity, driver status and next primary collection |
| `data/loads.csv` | 44 requests with cargo, pickup/delivery windows, revenue and verification flags |
| `data/sailings.csv` | 24 fictional departures across Matnog–Allen and Liloan–Surigao |
| `data/history.csv` | 900 synthetic completed trips, including unverified records that training excludes |
| `sample_results/` | Reproducible baseline allocation, full candidates, rejection audit and summary JSON |
| `tests/` | Constraint, resource-allocation, cost, learning and Streamlit interaction tests |
| `DATA_DICTIONARY.md` | Field definitions, units and modelling assumptions |

Regenerate inputs and the saved example:

```bash
python generate_data.py --seed 42
python model.py
python -m pytest tests -q
```

The app reads the four CSVs for seed 42. Other sidebar seeds generate new operational inputs in memory. The cached learning model always uses the bundled `history.csv`; it stays fixed when comparing scenarios. Restart the app after changing the CSVs to clear its caches.

## Model design

### 1. Apply hard rules

Only current, verified data enters matching. The model excludes hazardous, temperature-controlled, high-value and crane-handled freight; checks packaging and dimensions; and limits the pilot to supported hubs and dry vans. Trucks need a committed next northbound collection and a full initial driving block. Davao freight needs confirmed receiving/cross-dock capacity.

Bundles must fit pallet, payload, volume, individual pallet dimensions, gross weight, and simplified front/rear axle-group limits. Food and general cargo are segregated, and food requires a clean truck. Receiver capacity is checked per trip. Pickup loading must finish before every load's pickup deadline.

Each road segment is broken into at most 8-hour driving blocks with 10-hour rests. Short ferry trips do not reset the driving budget. At both ports, arrival plus queue must meet the sailing cutoff. Capacity and prebooking eligibility must be verified. After the second crossing, delivery and unloading must fit the confirmed window, with at least 12 hours remaining before the committed northbound collection.

The configurable delay buffer is split across crossings, so it can cause a second sailing to become infeasible. Weather disruption adds another 0–10 hours per crossing. No commercial score can bypass these timing checks.

### 2. Generate shared-hub bundles

Enumerate combinations of up to four compatible shipments collected at one hub and delivered to one destination hub. Each truck serves its own recovery base. Retain every feasible sailing pair for each bundle, rather than fixing the individually best ferry plan before fleet allocation.

The solution is restricted to this candidate space. It is not a full vehicle-routing, multi-stop, 3D packing or alternative-corridor model.

### 3. Learn extra transit delay

A random forest predicts `actual_extra_delay_hours` from planning-time weather risk, queue allowance, unbooked crossings, road distance and fill. Only verified records are used. Chronological blocks allocate 60% to training, 20% to residual calibration, and 20% to untouched testing. Actual delay and realised cost are never predictors.

The model reports held-out mean absolute error against a training-mean baseline. The calibration residual distribution supplies an approximate probability of meeting the available delivery/recovery slack. The app also reports empirical test coverage of a nominal 90% upper bound. The synthetic generator intentionally contains learnable relationships; these metrics provide no evidence of performance on real routes.

The reliability estimate simplifies connection cascades and conditional residual distributions. The hard timing checks use an explicit independent scenario buffer. A predicted high reliability never overrides an infeasible sailing connection.

### 4. Score and allocate

Default score:

```text
100 × [0.60 × (trip contribution / 100,000)
     + 0.20 × estimated service reliability
     + 0.10 × (contractual shipments / bundle limit)
     + 0.10 × loaded road kilometres / total road kilometres]
```

Sidebar weights are normalised to sum to one. Contribution can be negative; it is not clipped. Coverage is a soft contractual preference, with a separate destination/account audit. There are no hard service quotas in this prototype.

Binary variable `x[j]` selects candidate `j`. SciPy's mixed-integer solver maximises total weighted score subject to:

```text
sum(x[j] for each truck) <= 1
sum(x[j] containing each load) <= 1
sum(x[j] using each sailing) <= available vehicle slots
x[j] in {0, 1}
```

Plans below the minimum booked revenue are held by default. The exception switch admits them for explicit dispatcher review. Plans with nonpositive incremental value or score remain unallocated. The solver has a 20-second limit and a 0.1% relative-gap tolerance; the returned status and gap are recorded. A time-limited incumbent is never described as proven optimal. Resources are independently checked after solving.

This optimises the stated business score over the generated bundles; it does not promise maximum pure profit or a globally optimal vehicle-routing solution.

### 5. Explain, review and retain outcomes

Every selected plan includes its truck, manifest, sailings, time windows, cost components and score drivers. A demo dispatcher can approve, request modification or reject; each record includes the run fingerprint and candidate ID. Session decisions do not book a ferry, accept cargo, persist after the browser session, or constitute verified actual outcomes.

The learning step is demonstrated through verified synthetic historical outcomes. For a pilot, collect actual cost, delay, delivery performance and claims; validate them before adding rows to `history.csv`, retraining, and reviewing a new model version. Weekly outcome review and production data connections remain implementation work.

## Economics and case targets

```text
Trip contribution = revenue - road cost - ferry/port charges - other variable costs
Incremental gain vs empty = revenue - (loaded-trip cost - empty repositioning cost)
Fleet contribution = -all eligible trucks' empty baseline cost + selected trips' incremental gain
```

The fleet calculation retains empty-return costs for unmatched eligible trucks. The baseline assumes feasible empty repositioning and does not independently optimise empty sailing slots. Loaded-road-km share includes all eligible returning trucks in its denominator, rather than showing only selected trucks. Sea distance is excluded.

The case's PHP 128,000 less PHP 47,000, PHP 31,500 and PHP 16,500 gives PHP 33,000 contribution. Candidate-specific dummy costs are recalculated and will differ from that illustration. Ownership, tax, financing, claims and spoilage are excluded.

| Case measure | Prototype treatment |
| --- | --- |
| At least 85% pass dispatcher feasibility review | Requires actual dispatcher outcomes; not claimed from synthetic rule checks |
| At least 70% loaded southbound kilometres | Calculated across the eligible fleet's planned road movement |
| At least PHP 110,000 average revenue | Shown against recommended revenue; minimum is configurable |
| At least 90% on-time delivery | Forecast reliability shown; actual target achievement requires observed delivery outcomes |
| No safety or unapproved-booking incident | Hard exclusions and review gate demonstrated; no live bookings exist |

Before a real pilot, validate vessel restrictions and schedules, exact equipment/axles, cargo classes, road/driver policies, insurance, actual tariff/cost data, loading plans, dock calendars and real outcome quality. These are operational data gaps, not claims that the synthetic prototype has resolved them.

## Technical references

- [Streamlit app testing](https://docs.streamlit.io/develop/concepts/app-testing/get-started)
- [SciPy mixed-integer linear programming](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
- [scikit-learn RandomForestRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestRegressor.html)
