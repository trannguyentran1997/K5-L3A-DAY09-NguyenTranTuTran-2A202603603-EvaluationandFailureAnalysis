"""Orchestrator: handoff chỉ có field allowlist và tool đọc, không mang secret qua ranh giới.

    python -m pytest -q tests/test_orchestrator_extra.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab8.handoff import ALLOWED_FIELDS, READONLY_TOOLS, HandoffError, make_handoff
from lab8.shapes import SHAPES
from tests.conftest import BY_ID

run_claim = SHAPES["orchestrator"]
WITH_ORDER = [cid for cid, row in sorted(BY_ID.items()) if row["order_id"]]


def _handoff(result) -> dict:
    events = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))["events"]
    handoffs = [e["payload"] for e in events if e["kind"] == "handoff"]
    assert len(handoffs) == 1
    return handoffs[0]


@pytest.mark.parametrize("claim_id", WITH_ORDER)
def test_handoff_is_allowlisted_and_read_only(public_db, claim_id):
    handoff = _handoff(run_claim(claim_id, seed=11, store_path=str(public_db)))
    assert set(handoff) <= ALLOWED_FIELDS
    assert handoff["contract_version"] == "handoff.v1"
    assert set(handoff["allowed_tools"]) <= READONLY_TOOLS
    assert handoff["facts"] == {}
    assert handoff["claim_id"] == claim_id


@pytest.mark.parametrize("claim_id", sorted(BY_ID))
def test_no_parent_secret_or_ticket_in_trace(public_db, claim_id):
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    body = Path(result.trace_path).read_text(encoding="utf-8")
    for token in ("CANARY_SECRET_", "parent_secret", "raw_headers", "Bearer", BY_ID[claim_id]["ticket"]):
        assert token not in body


def test_missing_order_stops_before_handoff(public_db):
    """C-004 thiếu mã đơn: không giao việc cho investigator."""
    result = run_claim("C-004", seed=11, store_path=str(public_db))
    events = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))["events"]
    assert result.status == "needs_info"
    assert not [e for e in events if e["kind"] == "handoff"]


def test_handoff_rejects_write_tool():
    with pytest.raises(HandoffError):
        make_handoff(
            request_id="REQ-X",
            claim_id="C-001",
            task="investigate_claim",
            facts={},
            allowed_tools=["lookup_order", "issue_refund"],
        )
