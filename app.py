"""Streamlit demonstration of the PH Island Trucking case."""
from dataclasses import asdict
from io import BytesIO
from pathlib import Path
import json
import zipfile
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from generate_data import BASE, make_data
from model import Settings, load_data, run_model, train_delay_model

ROOT = Path(__file__).parent
st.set_page_config(page_title="Island Backhaul | Dispatch Lab", page_icon="🚚", layout="wide")
st.markdown("""<style>
 .block-container {padding-top:2.2rem; padding-bottom:3rem; max-width:1500px;}
 [data-testid="stMetric"] {background:white; padding:1rem; border-radius:12px; border:1px solid #e3e9ef;}
 [data-testid="stMetricValue"], [data-testid="stMetricValue"] > div {font-size:1.45rem !important;}
 h1 {letter-spacing:-.04em;} [data-testid="stSidebar"] {border-right:1px solid #e3e9ef;}
 .eyebrow {color:#087F8C; font-weight:700; letter-spacing:.15em; font-size:.75rem;}
 </style>""", unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def learned_model():
    return train_delay_model(load_data(ROOT / "data")["history"])


@st.cache_data(show_spinner=False, max_entries=12)
def solve(seed, scenario, settings_dict):
    data = load_data(ROOT / "data") if seed == 42 else make_data(seed)
    if scenario == "First crossing cancelled":
        mask = data["sailings"].leg.eq("Matnog-Allen") & data["sailings"].sailing_id.isin(["MA-01", "MA-02"])
        data["sailings"].loc[mask, "cancelled"] = True
    elif scenario == "Ferry capacity squeeze":
        data["sailings"]["available_slots"] = 1
    elif scenario == "Stale source records":
        for name in ["trucks", "loads", "sailings"]:
            data[name]["updated_at"] = BASE - pd.Timedelta(hours=24)
    return run_model(data, Settings(**settings_dict), now=BASE, learned=learned_model()), data


def money(x):
    return f"PHP {x:,.0f}"


def csv_bytes(frame):
    frame = frame.copy()
    if "timeline" in frame:
        frame = frame.drop(columns="timeline")
    if "load_ids" in frame:
        frame["load_ids"] = frame.load_ids.apply(lambda ids: " | ".join(ids))
    return frame.to_csv(index=False).encode("utf-8")


def export_zip(result):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["selected", "candidates", "audit", "rejection_counts"]:
            archive.writestr(f"{name}.csv", csv_bytes(result[name]))
        archive.writestr("summary.json", json.dumps({k: result[k] for k in ["run_id", "settings", "metrics", "solver"]}, indent=2))
    return buffer.getvalue()


with st.sidebar:
    st.markdown("### Dispatch lab")
    st.caption("One planning run. Two island crossings. Human approval.")
    with st.form("scenario_form"):
        scenario = st.selectbox("Scenario", ["Baseline pilot", "First crossing cancelled", "Ferry capacity squeeze", "Stale source records"])
        seed = st.number_input("Synthetic data seed", 1, 9999, 42)
        minimum = st.number_input("Minimum revenue per trip (PHP)", 0, 300000, 110000, 5000)
        exceptions = st.checkbox("Allow revenue exceptions for review", value=False)
        enable_davao = st.checkbox("Enable verified Davao branch", value=True)
        bundle_size = st.slider("Maximum shipments per truck", 1, 4, 4)
        weather = st.slider("Additional weather disruption", 0., 1., 0., .1)
        buffer = st.slider("Total extra delay buffer (hours)", 0, 36, 6, 2)
        road_rate = st.slider("Road cost per kilometre (PHP)", 20, 55, 31)
        st.markdown("**Ranking weights**")
        wc = st.slider("Contribution", 0, 10, 6)
        wr = st.slider("Service reliability", 0, 10, 2)
        wg = st.slider("Contract coverage", 0, 10, 1)
        wk = st.slider("Loaded kilometres", 0, 10, 1)
        submitted = st.form_submit_button("Run matching model", type="primary", width="stretch")
    st.caption("Clock fixed at 09 Nov 2026, 06:00 PHT. All inputs are fictional. Changing a control takes effect after Run.")

total_weight = wc + wr + wg + wk
if total_weight == 0:
    st.warning("Choose at least one non-zero ranking weight before running.")
    st.stop()
settings = Settings(minimum_revenue=int(minimum), allow_revenue_exceptions=exceptions,
                    enable_davao=enable_davao, max_bundle=bundle_size, weather_shock=weather,
                    delay_buffer_hours=buffer, road_cost_per_km=road_rate,
                    contribution_weight=wc/total_weight, reliability_weight=wr/total_weight,
                    coverage_weight=wg/total_weight, loaded_km_weight=wk/total_weight)
if submitted or "result" not in st.session_state:
    with st.spinner("Checking constraints, generating bundles and allocating fleet capacity…"):
        result, data = solve(int(seed), scenario, asdict(settings))
        st.session_state.result = result
        st.session_state.data = data
        st.session_state.active_scenario = scenario
result, data = st.session_state.result, st.session_state.data
m = result["metrics"]
selected, candidates = result["selected"], result["candidates"]

st.markdown('<div class="eyebrow">ARCHIPELAGO LOGISTICS · SYNTHETIC PILOT</div>', unsafe_allow_html=True)
st.title("Turn the return trip into revenue")
st.write("Match Luzon shipper demand with empty trucks returning to Mindanao, while protecting the next northbound collection.")
st.caption(f"{st.session_state.active_scenario}  ·  Run {result['run_id']}  ·  Manila → Matnog → Allen → Liloan → Surigao → Mindanao")
st.info("Classroom demonstration: every shipper, sailing, rate and equipment limit is synthetic. Recommendations require dispatcher review. This app never accepts cargo or books ferries.")

cols = st.columns(4)
cols[0].metric("Matched trucks", f"{m['recommended_trucks']} / {m['eligible_trucks']}", f"{m['matched_loads']} loads matched")
cols[1].metric("Revenue (PHP)", f"{m['revenue_php']:,.0f}")
cols[2].metric("Gain (PHP)", f"{m['incremental_gain_php']:,.0f}", help="Incremental gain compared with empty repositioning.")
cols[3].metric("Loaded road km", f"{m['fleet_loaded_km_ratio']:.0%}", "Pilot target 70%", delta_color="off")

tabs = st.tabs(["Fleet recommendations", "Trip detail & review", "Rejected & unmatched", "AI model & economics", "Data & assumptions"])
with tabs[0]:
    st.subheader("Recommended southbound plan")
    st.write("The solver allocates each truck and shipment once and respects the total vehicle slots on both ferry legs.")
    if selected.empty:
        st.warning("No plans meet this scenario's hard rules and commercial settings. Inspect the audit or adjust the scenario.")
    else:
        display = selected[["candidate_id", "truck_id", "load_ids", "destination", "pallets", "fill_ratio", "revenue_php", "contribution_php", "estimated_service_reliability", "commercial_exception"]].copy()
        display["load_ids"] = display.load_ids.apply(lambda ids: ", ".join(ids))
        st.dataframe(display, hide_index=True, width="stretch", column_config={
            "candidate_id": "Plan", "truck_id": "Truck", "load_ids": "Shipments", "destination": "Destination", "pallets": "Pallets",
            "commercial_exception": "Revenue exception",
            "fill_ratio": st.column_config.ProgressColumn("Pallet fill", min_value=0., max_value=1., format="percent"),
            "estimated_service_reliability": st.column_config.NumberColumn("Estimated reliability", format="percent"),
            "revenue_php": st.column_config.NumberColumn("Revenue (PHP)", format="%.0f"),
            "contribution_php": st.column_config.NumberColumn("Contribution (PHP)", format="%.0f")})
        chart = selected[["truck_id", "revenue_php", "variable_cost_php", "contribution_php"]].melt("truck_id", var_name="Measure", value_name="PHP")
        chart["Measure"] = chart["Measure"].map({"revenue_php": "Revenue", "variable_cost_php": "Variable cost", "contribution_php": "Contribution"})
        fig = px.bar(chart, x="truck_id", y="PHP", color="Measure", barmode="group",
                     color_discrete_sequence=["#087F8C", "#B3C2CE", "#E49B3F"])
        fig.update_layout(legend_title_text="", xaxis_title="Truck", margin=dict(t=15, b=10), height=340)
        st.plotly_chart(fig, width="stretch")
    st.caption(f"Solver: {result['solver']['status']}. Optimality applies to the generated shared-hub bundles of up to {result['settings']['max_bundle']} shipments, using the selected weights.")
    st.download_button("Download this run", export_zip(result), "island_backhaul_run.zip", "application/zip")
    st.markdown("**Commercial check**")
    st.write(f"Average recommended revenue is {money(m['average_revenue_php'])}; the case target is PHP 110,000. "
             f"Average pallet fill is {m['average_fill_ratio']:.0%}. These are simulated planning results.")

with tabs[1]:
    if selected.empty:
        st.write("Run a feasible scenario to review a trip.")
    else:
        plan_id = st.selectbox("Recommended plan", selected.candidate_id.tolist())
        plan = selected.loc[selected.candidate_id.eq(plan_id)].iloc[0]
        manifest = data["loads"].loc[data["loads"].load_id.isin(plan.load_ids)]
        truck = data["trucks"].loc[data["trucks"].truck_id.eq(plan.truck_id)].iloc[0]
        left, right = st.columns([2, 1])
        with left:
            st.subheader(f"{plan.truck_id} · {plan.pickup_hub} to {plan.destination}")
            st.write(f"Consolidate {len(plan.load_ids)} compatible shipments, using {plan.pallets} pallets and {plan.weight_kg:,.0f} kg. "
                     f"Sailings: {plan.sailing_1} and {plan.sailing_2}.")
            st.dataframe(manifest[["load_id", "shipper", "cargo_class", "pallets", "weight_kg", "revenue_php", "contractual"]], hide_index=True, width="stretch")
        with right:
            st.metric("Trip contribution", money(plan.contribution_php))
            st.metric("Recovery slack after delivery", f"{plan.recovery_slack_hours:.1f} hours")
            st.caption(f"Required recovery buffer: {result['settings']['recovery_buffer_hours']:.0f} hours. Next collection: {plan.northbound_collection:%d %b %H:%M PHT}.")
        st.write(f"Guarded road arrival: **{plan.guarded_arrival:%d %b %H:%M PHT}**. "
                 f"Planned unloading: **{plan.delivery_start:%d %b %H:%M}–{plan.delivery_end:%d %b %H:%M PHT}**. "
                 f"Receiver deadline: **{plan.latest_delivery:%d %b %H:%M PHT}**.")
        timeline = pd.DataFrame(plan.timeline)
        timeline["stage"] = [f"{i+1:02}. {a}" for i, a in enumerate(timeline.activity)]
        # Naive local timestamps avoid browser-side conversion out of PHT.
        for col in ["start", "end"]:
            timeline[col] = pd.to_datetime(timeline[col]).dt.tz_localize(None)
        fig = px.timeline(timeline, x_start="start", x_end="end", y="stage", color="activity",
                          color_discrete_sequence=px.colors.qualitative.Safe)
        fig.update_yaxes(autorange="reversed", title=None)
        fig.update_layout(showlegend=False, height=max(420, len(timeline)*25), xaxis_title="Philippine time (UTC+8)", margin=dict(t=10, l=0, r=10))
        st.plotly_chart(fig, width="stretch")
        front = truck.tare_front_kg + (manifest.weight_kg * manifest.front_payload_fraction).sum()
        rear = truck.tare_rear_kg + (manifest.weight_kg * (1-manifest.front_payload_fraction)).sum()
        st.caption(f"Planning axle-group loads: front {front:,.0f}/{truck.front_group_limit_kg:,.0f} kg; rear {rear:,.0f}/{truck.rear_group_limit_kg:,.0f} kg. "
                   "This simplified load-distribution check requires a physical loading plan and weighbridge validation before use.")
        st.markdown("**Why this plan ranks highly**")
        st.write(f"Score {plan.score:.1f}: contribution {money(plan.contribution_php)}, estimated service reliability "
                 f"{plan.estimated_service_reliability:.0%}, {plan.contractual_loads} contractual shipments, and {plan.loaded_km_ratio:.0%} loaded road distance. "
                 f"Estimated extra delay from the learned model: {plan.predicted_delay_hours:.1f} hours.")
        if plan.commercial_exception:
            st.warning(f"Revenue is below {money(result['settings']['minimum_revenue'])}. A dispatcher exception reason is required.")
        st.markdown("**Record a demo dispatcher decision**")
        with st.form("decision_form"):
            decision = st.radio("Decision", ["Approve", "Modify", "Reject"], horizontal=True)
            reviewed = st.checkbox("I reviewed cargo, physical loading, driver policy, appointments and sailing source data")
            reason = st.text_input("Review note / exception reason")
            record = st.form_submit_button("Record demo decision")
        if record:
            if decision == "Approve" and not reviewed:
                st.error("Complete the dispatcher review before demo approval.")
            elif (decision != "Approve" or plan.commercial_exception) and len(reason.strip()) < 10:
                st.error("Provide a review note of at least 10 characters.")
            else:
                log = st.session_state.setdefault("decisions", [])
                log.append(dict(recorded_at=pd.Timestamp.now(tz="Asia/Manila").isoformat(),
                                run_id=result["run_id"], candidate_id=plan.candidate_id,
                                truck_id=plan.truck_id, load_ids=" | ".join(plan.load_ids),
                                decision=decision, reviewed=reviewed, note=reason))
                st.success("Demo decision recorded for this run. No operational booking was made. Modified plans require a new model run.")
        if st.session_state.get("decisions"):
            log = pd.DataFrame(st.session_state.decisions)
            st.dataframe(log, hide_index=True, width="stretch")
            st.download_button("Download decision log", csv_bytes(log), "demo_dispatcher_decisions.csv", "text/csv")
        st.caption("Demo decisions are kept in this browser session; download them to retain a record. A changed scenario has a different run ID.")

with tabs[2]:
    st.subheader("Every load has an explanation")
    audit = result["audit"]
    entity = st.selectbox("Audit entity", ["loads", "trucks", "sailings"])
    rows = audit.loc[audit.entity.eq(entity)]
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("Eligible means the source and pilot rules passed. Capacity, timing and commercial checks occur when complete bundles are generated.")
    coverage = data["loads"][["load_id", "destination", "contractual"]].merge(audit.loc[audit.entity.eq("loads"), ["id", "reason"]], left_on="load_id", right_on="id")
    coverage["selected"] = coverage.reason.eq("Selected in fleet recommendation")
    st.markdown("**Coverage audit**")
    st.dataframe(coverage.groupby(["destination", "contractual"], as_index=False).agg(loads=("load_id", "count"), selected=("selected", "sum")), hide_index=True, width="stretch")
    st.caption("Coverage is a configurable preference. This prototype has no hard account quotas or geographic service guarantees.")
    with st.expander("Bundle constraint attempts"):
        st.dataframe(result["rejection_counts"], hide_index=True, width="stretch")
        st.caption("Counts are attempted bundle/sailing combinations, not counts of distinct rejected shipments. A bundle can fail different routes for different reasons.")
    with st.expander("Ranked feasible alternatives"):
        if not candidates.empty:
            frame = candidates.head(200)[["candidate_id", "truck_id", "load_ids", "sailing_1", "sailing_2", "score", "revenue_php", "commercial_eligible"]].copy()
            frame["load_ids"] = frame.load_ids.apply(lambda ids: " | ".join(ids))
            st.dataframe(frame, hide_index=True, width="stretch")
            st.caption(f"Showing at most 200 of {len(candidates):,} feasible candidates. Download the run for the complete table.")

with tabs[3]:
    st.subheader("Rules → predict delay → rank → allocate → review")
    st.write("Hard rules reject invalid cargo and infeasible capacity, driver blocks, pickup windows, ferry connections, delivery windows and northbound recovery. "
             "A random forest learns extra transit delay from verified synthetic history. A binary optimisation model then selects the highest total score across the fleet.")
    st.latex(r"\max \sum_j x_j\,100\left(w_c\frac{C_j}{100000}+w_r R_j+w_g\frac{K_j}{B}+w_k L_j\right)")
    st.caption("x = select a candidate, C = trip contribution in PHP, R = empirical service reliability estimate, K = contractual shipments, B = bundle limit, L = loaded-road-km share. "
               "One candidate per truck; each load once; ferry usage within slots. Empty repositioning remains available.")
    stats = result["learned"]["metrics"]
    c = st.columns(3)
    c[0].metric("Delay model test MAE", f"{stats['mae_hours']:.2f} hours")
    c[1].metric("Mean-delay baseline MAE", f"{stats['baseline_mae_hours']:.2f} hours")
    c[2].metric("P90 upper-bound test coverage", f"{stats['p90_test_coverage']:.0%}")
    st.write(f"Of 900 synthetic trips, {stats['excluded_unverified']} unverified rows are excluded. The remaining rows use chronological blocks: "
             f"{stats['train_rows']} training, {stats['calibration_rows']} residual calibration and {stats['test_rows']} untouched testing. "
             "No actual delay or realised cost is used as an input feature.")
    left, right = st.columns(2)
    with left:
        test = result["learned"]["test_predictions"]
        fig = px.scatter(test, x="actual_extra_delay_hours", y="predicted_delay_hours", opacity=.6,
                         labels={"actual_extra_delay_hours": "Actual extra delay (h)", "predicted_delay_hours": "Predicted extra delay (h)"})
        fig.add_trace(go.Scatter(x=[0, 35], y=[0, 35], mode="lines", line=dict(color="#B3C2CE", dash="dash"), showlegend=False))
        fig.update_layout(height=340, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    with right:
        imp = result["learned"]["importance"].sort_values("importance")
        fig = px.bar(imp, y="feature", x="importance", orientation="h", color_discrete_sequence=["#087F8C"])
        fig.update_layout(height=340, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
    st.caption("Synthetic accuracy demonstrates the workflow only. Reliability uses the calibration residual distribution and available appointment slack; "
               "it is an approximation and does not simulate missed-connection cascades. Severe weather may be outside training support. "
               "Hard timing uses an explicit scenario buffer independently of the learned score.")
    st.markdown("**Fleet economics against empty return**")
    economics = pd.DataFrame([
        {"Measure": "Southbound revenue", "Empty return": 0, "Recommended fleet": m["revenue_php"]},
        {"Measure": "Fleet variable cost", "Empty return": m["empty_baseline_cost_php"], "Recommended fleet": m["revenue_php"]-m["fleet_contribution_php"]},
        {"Measure": "Fleet contribution before ownership", "Empty return": -m["empty_baseline_cost_php"], "Recommended fleet": m["fleet_contribution_php"]},
    ])
    st.dataframe(economics, hide_index=True, width="stretch")
    st.write("Trip contribution = revenue − road operating cost − ferry/port charges − driver, handling and administration. "
             "Gain versus empty return = revenue − extra cost of carrying the backhaul. Unmatched eligible trucks still incur their empty repositioning cost in fleet contribution.")
    st.caption("The empty-return comparison is an illustrative cost baseline, assuming feasible repositioning. It does not separately optimise empty-truck ferry slots or forecast empty-trip delays. "
               "Ownership costs, tax, spoilage, claims and financing are excluded.")
    st.markdown("**Learning from pilot outcomes**")
    st.write("The prototype retrains when verified history.csv is changed and the app is restarted or its resource cache is cleared. "
             "Dispatcher decisions are review records, not verified delivery outcomes. Only verified completed trips enter training. "
             "In a live pilot, collect actual arrival, cost, claims, approval and rejection reasons; review drift and performance weekly before releasing a new model.")

with tabs[4]:
    st.subheader("Fictional inputs, explicit assumptions")
    st.write("The bundled seed 42 dataset contains 7 trucks, 44 shipper requests, 24 ferry departures and 900 historical trips. "
             "Other seeds regenerate operational inputs while the demonstration keeps the same history-trained model for scenario comparison.")
    dataset = st.selectbox("Dataset", list(data))
    st.dataframe(data[dataset], hide_index=True, width="stretch")
    st.download_button(f"Download {dataset}.csv", csv_bytes(data[dataset]), f"{dataset}.csv", "text/csv")
    st.markdown("""
    - The case mentions both 10-wheelers and tractor/40-foot dry vans. This demo standardises on a fictional 40-foot dry van: 20 pallets, 18,000 kg payload and 60 m³. Confirm the actual equipment before a pilot.
    - Freight is prepositioned at one consolidation hub in Manila or Calamba and delivered to one receiving hub in Cagayan de Oro or Davao. No door-to-door collection, multiple delivery stops, alternative physical corridors or 3D packing solver are included.
    - Bundles have at most four shipments; food and general goods remain segregated. Dimensions, total volume, gross weight and a simplified planned axle split are checked. Actual loading still needs physical validation.
    - Davao requires confirmed receiving/cross-dock capacity. Each truck serves its own northbound recovery base. Receiver pallet capacity is a per-trip check; no shared hourly dock scheduling is modelled.
    - Road driving inputs are 14 hours to Matnog, 12 hours Allen–Liloan, and 6 hours to CDO or 11 hours to Davao. Driving is split into at most 8-hour blocks separated by 10-hour rests. These are fictional policy settings, not a claim about Philippine legal limits.
    - Remaining initial driver hours must cover a full 8-hour block. Short ferry crossings do not reset the driving budget. Continuous eligible waiting of at least 10 hours can count as rest; port queues, loading and unloading do not.
    - Both ferry legs need verified capacity and prebooking eligibility. Arrival plus port queue must meet the cutoff. Aggregate vehicle slots are enforced. All displayed sailings are invented, and no reservations are held.
    - A configurable delay buffer is split across the two crossings. The weather slider adds 10 hours per crossing at maximum shock. Recovery requires 12 hours after unloading before the committed northbound collection.
    - Pilot cargo exclusions and the case's PHP 110,000 revenue threshold are represented. The PHP 1 million high-value cutoff, freshness limit of 12 hours, axle limits and road costs are additional demo assumptions.
    - The case's illustrative PHP 128,000 revenue less PHP 95,000 variable cost equals PHP 33,000 contribution. Demo candidates recompute their own cost; they do not force that result.
    """)
    st.write("To substitute data, preserve the CSV schemas and timezone-aware timestamps in data/, regenerate the sample model results, and restart Streamlit. "
             "For live use, replace the fixed clock with current Philippine time and connect verified dispatch, shipper and ferry sources.")
    with st.expander("Active run settings"):
        st.json(result["settings"])
