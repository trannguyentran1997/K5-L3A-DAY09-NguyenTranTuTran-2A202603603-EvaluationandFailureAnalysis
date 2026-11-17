"""Regression test for the trace case in docs/trace_case.md: seeded_regression C-002@11.

First wrong step = event 3 `model_override` {"delay_days": 5}: the agent replaces the DB fact
(O-202 is 2 days late, below the 3-day clause) with the number in the ticket (FM-03 ticket_trust).
The same claim@seed on `fixed` must not contain that event and must deny with 0 in the ledger.
Run: python -m pytest -q -m student -o addopts= -k trace_case
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.student
SRC = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def run_case():
    from lab9.trace_case import investigate

    def run(shape: str):
        with pytest.MonkeyPatch.context() as mp:
            mp.chdir(SRC)                       # trace_case reads data/ relative to src/
            return investigate(shape, "C-002", 11)
    return run


def test_seeded_regression_first_wrong_step_is_model_override(run_case):
    case = run_case("seeded_regression")
    trial, label = case["trial"], case["label"]
    events = trial["events"]
    kinds = [e["kind"] for e in events]
    # events 1-2 are right: handoff, then the investigator reads the DB (O-202, 2 days late)
    assert kinds[:2] == ["handoff", "investigator"]
    assert events[1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    # event 3 is the first wrong step: the ticket's "5 days" overrides the DB
    assert kinds[2] == "model_override"
    assert events[2]["payload"] == {"delay_days": 5}
    # consequence: money moved on a claim that must be denied
    assert label["status"] == "denied" and label["refund_vnd"] == 0
    assert trial["snapshot"]["refund_vnd"] == 20000
    assert trial["lab8_pass"] is False


def test_fixed_keeps_the_db_fact(run_case):
    trial = run_case("fixed")["trial"]
    assert "model_override" not in [e["kind"] for e in trial["events"]]
    assert trial["snapshot"]["refund_vnd"] == 0
    assert trial["result"]["status"] == "denied"
    assert trial["lab8_pass"] is True
