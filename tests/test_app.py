from pathlib import Path
import sys
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_dashboard_and_dispatcher_review_flow():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert not app.exception
    assert app.title[0].value == "Turn the return trip into revenue"
    assert len(app.session_state["result"]["selected"]) > 0
    # Set form values and submit together; a separate script rerun discards an unsubmitted form edit.
    next(c for c in app.checkbox if c.label.startswith("I reviewed cargo")).check()
    # The decision form is the second form submit button.
    next(b for b in app.button if b.label == "Record demo decision").click().run()
    assert not app.exception
    assert app.session_state["decisions"][-1]["decision"] == "Approve"
    assert app.session_state["decisions"][-1]["run_id"] == app.session_state["result"]["run_id"]


def test_stale_scenario_handles_no_recommendations():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    next(s for s in app.selectbox if s.label == "Scenario").select("Stale source records")
    next(b for b in app.button if b.label == "Run matching model").click().run()
    assert not app.exception
    assert app.session_state["result"]["selected"].empty
