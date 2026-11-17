"""Crash và gọi lại trên từng shape, không chỉ trên host.

`lab8.crash_test` chỉ kiểm host và swarm; T12 chỉ kiểm một điểm crash. File này
chạy cả ba điểm crash (`before_effect`, `after_effect_before_checkpoint`,
`after_checkpoint`) và kịch bản gọi lại nhiều lần trên cả bốn shape.

Gắn marker `student`: shape chưa viết thì đỏ, swarm xanh ngay.

    python -m pytest -q -m student -o addopts= tests/test_crash_shapes.py
    python -m pytest -q -m student -o addopts= tests/test_crash_shapes.py -k workflow
"""

from __future__ import annotations

import time

import pytest

from lab8.db import connect
from lab8.durability import InjectedCrash
from lab8.metrics import trial_pass
from lab8.shapes import SHAPES
from tests.conftest import BY_ID

ALL_SHAPES = ["workflow", "single", "orchestrator", "swarm"]
CRASH_POINTS = ["before_effect", "after_effect_before_checkpoint", "after_checkpoint"]

pytestmark = pytest.mark.student


def _ledger(store) -> tuple[int, int, int]:
    """(số dòng refund, tổng tiền, số audit refund_committed) của C-012."""
    conn = connect(store)
    try:
        rows = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_vnd), 0) AS total FROM refund_ledger WHERE claim_id = 'C-012'"
        ).fetchone()
        audits = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE claim_id = 'C-012' AND event_type = 'refund_committed'"
        ).fetchone()
        return int(rows["n"]), int(rows["total"]), int(audits["n"])
    finally:
        conn.close()


@pytest.mark.parametrize("shape", ALL_SHAPES)
@pytest.mark.parametrize("point", CRASH_POINTS)
def test_crash_then_resume_pays_once(public_db, shape, point):
    with pytest.raises(InjectedCrash):
        SHAPES[shape]("C-012", seed=11, store_path=str(public_db), crash_at=point)

    count, _, _ = _ledger(public_db)
    if point == "before_effect":
        assert count == 0, "crash trước khi ghi mà ledger đã có dòng"
    else:
        assert count == 1, "crash sau khi ghi thì dòng refund phải còn"

    started_at = time.time()
    result = SHAPES[shape]("C-012", seed=11, store_path=str(public_db))
    conn = connect(public_db)
    try:
        passed, reason = trial_pass(result.as_dict(), BY_ID["C-012"]["expected"], conn, started_at=started_at)
    finally:
        conn.close()
    assert passed, reason
    assert _ledger(public_db) == (1, 35000, 1)


@pytest.mark.parametrize("shape", ALL_SHAPES)
def test_repeated_calls_keep_one_refund(public_db, shape):
    results = [SHAPES[shape]("C-012", seed=seed, store_path=str(public_db)) for seed in (11, 22, 33)]
    assert [r.status for r in results] == ["resolved"] * 3
    assert all(r.proposal_amount == 35000 for r in results)
    assert _ledger(public_db) == (1, 35000, 1)


@pytest.mark.parametrize("shape", ALL_SHAPES)
def test_retry_after_crash_is_replay_not_new_write(public_db, shape):
    """Đã có dòng refund thì host trả `idempotent_replay` trước mọi điểm crash.

    Lần gọi lại mang crash_at vẫn không crash và không ghi thêm: bằng chứng là
    lần gọi lại không đi vào nhánh ghi.
    """
    with pytest.raises(InjectedCrash):
        SHAPES[shape]("C-012", seed=11, store_path=str(public_db), crash_at="after_effect_before_checkpoint")
    for point in CRASH_POINTS[1:]:
        result = SHAPES[shape]("C-012", seed=11, store_path=str(public_db), crash_at=point)
        assert result.status == "resolved"
        assert result.proposal_amount == 35000
    assert _ledger(public_db) == (1, 35000, 1)
