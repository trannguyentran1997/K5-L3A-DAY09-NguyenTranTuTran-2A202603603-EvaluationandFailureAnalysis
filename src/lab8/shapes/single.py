"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.

Ranh giới code / model trong shape này:

- Model (MockLLM, gọi trong `decide`) chỉ chọn tool ĐỌC tiếp theo, hoặc dừng.
  Model không thấy ticket, không trả số tiền, không có tool ghi.
- Số tiền là `amount_vnd` do `compute_compensation` tính từ dòng order.
- Sau vòng lặp, code của shape gọi `durability.issue_refund` với quote đầy đủ.
- Trace chỉ ghi kết quả tool đã qua allowlist; không ghi ticket, claim row hay order row thô.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from lab8 import durability
from lab8.db import connect
from lab8.mock_llm import complete
from lab8.runtime import ToolRejected, run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.trace import Trace

SHAPE = "single"
MAX_STEPS = 8


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, claim_id: str, *, seed: int, crash_at: str | None) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    def done(status: str, amount: int = 0, reason: str | None = None) -> RunResult:
        trace.add("decision", {"status": status, "proposal_amount": int(amount), "reason": reason})
        return finish(
            conn,
            shape=SHAPE,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=amount,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )

    # Kết quả các tool đã gọi. run_react chỉ đưa lại kết quả gần nhất, nên decide tự gom.
    seen: dict[str, dict[str, Any]] = {}

    def decide(obs: dict[str, Any]) -> dict[str, Any]:
        last = obs.get("last_tool")
        if last:
            seen[last] = obs["last_result"]
            trace.add("observe", {"tool": last, "result": _safe_view(last, obs["last_result"])})
        action = _next_action(claim_id, seen)
        # Một lượt "suy nghĩ" của model. Prompt chỉ có tên tool đã xem, không có ticket.
        complete(budget, seed=seed, purpose="react", prompt=json.dumps(sorted(seen)) + "|" + _action_name(action))
        trace.add("act", {"action": _action_name(action)})
        return action

    try:
        loop = run_react(
            conn,
            budget,
            observation={"claim": {"claim_id": claim_id}},
            decide=decide,
            max_steps=MAX_STEPS,
        )
    except ToolRejected as exc:
        return done("failed", 0, f"tool_rejected:{exc}")

    final = loop["final"]
    if loop["stopped"] == "step_cap":
        return done("failed", 0, "step_cap")
    if final["status"] != "quote_ready":
        return done(final["status"], 0, final.get("reason"))

    # Từ đây là code, không phải model. Tiền lấy từ tool compute_compensation.
    quote = seen["compute_compensation"]
    trace.add("quote", quote)
    proposal = int(quote["amount_vnd"])
    if proposal <= 0:
        return done("denied", 0, quote.get("reason"))

    try:
        outcome = durability.issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except durability.InjectedCrash:
        trace.add("crash", {"at": crash_at})
        trace.write()
        raise
    trace.add("issue_refund", {"ok": outcome["ok"], "reason": outcome["reason"]})
    complete(budget, seed=seed, purpose="draft", prompt=f"outcome={outcome['reason']}")

    if not outcome["ok"]:
        return done("failed" if outcome["conflict"] else "denied", proposal, outcome["reason"])
    return done("resolved", proposal)


def _next_action(claim_id: str, seen: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Chính sách chọn tool của agent. Chỉ trả tool đọc hoặc final, không bao giờ trả số tiền."""
    if "get_claim_view" not in seen:
        return {"tool": "get_claim_view", "args": {"claim_id": claim_id}}
    claim = seen["get_claim_view"]
    if not claim.get("found"):
        return {"final": {"status": "failed", "reason": "unknown_claim"}}
    # Mã đơn lấy từ claim trong database, không đoán từ ticket.
    if not claim.get("order_id"):
        return {"final": {"status": "needs_info", "reason": "missing_order_id"}}
    scope = {"order_id": claim["order_id"], "principal_id": claim["principal_id"]}
    if "lookup_order" not in seen:
        return {"tool": "lookup_order", "args": scope}
    order_view = seen["lookup_order"]
    if not order_view.get("visible"):
        return {"final": {"status": "escalated", "reason": order_view.get("reason")}}
    if "lookup_refund_history" not in seen:
        # Chỉ để ghi nhận. Host tự trừ phần đã hoàn; shape không trừ.
        return {"tool": "lookup_refund_history", "args": scope}
    if "compute_compensation" not in seen:
        return {"tool": "compute_compensation", "args": {"order": order_view["order"]}}
    return {"final": {"status": "quote_ready"}}


def _action_name(action: dict[str, Any]) -> str:
    if "final" in action:
        return f"final:{action['final']['status']}"
    return str(action.get("tool"))


def _safe_view(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    """Bản ghi trace của một kết quả tool. Claim view có ticket nên chỉ giữ cờ."""
    if tool == "get_claim_view":
        return {
            "found": bool(result.get("found")),
            "claim_id": result.get("claim_id"),
            "has_order_id": bool(result.get("order_id")),
        }
    if tool == "lookup_order":
        # lookup_order đã allowlist 7 field; nhánh không visible chỉ có reason, order_id.
        return {key: result[key] for key in ("visible", "reason", "order") if key in result}
    return result
