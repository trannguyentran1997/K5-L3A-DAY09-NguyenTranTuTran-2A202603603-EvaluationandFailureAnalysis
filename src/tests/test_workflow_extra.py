"""Workflow: model không tham gia quyết định, trace không chứa ticket, claim lạ không làm sập.

    python -m pytest -q tests/test_workflow_extra.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab8.shapes import SHAPES
from tests.conftest import BY_ID

run_claim = SHAPES["workflow"]
CLAIM_IDS = sorted(BY_ID)


@pytest.mark.parametrize("claim_id", ["C-002", "C-004", "C-005", "C-006", "C-009"])
def test_no_model_call_when_no_refund_attempt(public_db, claim_id):
    """needs_info / escalated / quote 0: mọi quyết định là code, không gọi model lần nào."""
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    assert result.status in ("needs_info", "escalated", "denied")
    assert result.model_calls == 0


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_at_most_one_model_call(public_db, claim_id):
    """Model chỉ soạn câu trả lời, tối đa một lần."""
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    assert result.model_calls <= 1


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_trace_never_contains_ticket_text(public_db, claim_id):
    result = run_claim(claim_id, seed=11, store_path=str(public_db))
    body = Path(result.trace_path).read_text(encoding="utf-8")
    assert BY_ID[claim_id]["ticket"] not in body
    assert json.loads(body)["run_id"] == result.run_id


def test_unknown_claim_fails_cleanly(public_db):
    result = run_claim("C-999", seed=11, store_path=str(public_db))
    assert result.status == "failed"
    assert result.proposal_amount == 0
    assert result.refund_effects == []
    assert Path(result.trace_path).is_file()
