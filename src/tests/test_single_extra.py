"""Single ReAct: agent chỉ chọn tool đọc, dừng trong trần 8 bước, không thấy ticket.

    python -m pytest -q tests/test_single_extra.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab8.handoff import READONLY_TOOLS
from lab8.shapes import SHAPES
from lab8.shapes.single import MAX_STEPS
from tests.conftest import BY_ID

run_claim = SHAPES["single"]
CLAIM_IDS = sorted(BY_ID)


def _events(result) -> list[dict]:
    return json.loads(Path(result.trace_path).read_text(encoding="utf-8"))["events"]


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_agent_only_picks_read_tools_or_final(public_db, claim_id):
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    actions = [e["payload"]["action"] for e in _events(result) if e["kind"] == "act"]
    assert actions, "trace phải ghi các lượt chọn của agent"
    for action in actions:
        assert action in READONLY_TOOLS or action.startswith("final:"), action
    assert "issue_refund" not in actions


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_stays_within_step_cap(public_db, claim_id):
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    acts = [e for e in _events(result) if e["kind"] == "act"]
    assert len(acts) <= MAX_STEPS
    # Mỗi lượt một lần gọi model, cộng tối đa một lần soạn câu trả lời.
    assert result.model_calls <= MAX_STEPS + 1
    assert result.error_reason != "step_cap"


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_trace_never_contains_ticket_text(public_db, claim_id):
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    body = Path(result.trace_path).read_text(encoding="utf-8")
    assert BY_ID[claim_id]["ticket"] not in body


def test_refund_history_is_read_but_quote_stays_full(public_db):
    """T14: agent có đọc lịch sử hoàn tiền, nhưng proposal vẫn là quote đầy đủ."""
    result = run_claim("C-014", seed=11, store_path=str(public_db))
    actions = [e["payload"]["action"] for e in _events(result) if e["kind"] == "act"]
    assert "lookup_refund_history" in actions
    assert result.proposal_amount == 150000
    assert result.refund_effects[0]["amount_vnd"] == 120000
