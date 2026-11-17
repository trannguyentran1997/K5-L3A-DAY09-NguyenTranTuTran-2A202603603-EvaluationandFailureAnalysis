"""Shape C — orchestrator plus read-only investigators. Student work.

1. Build a handoff with `lab8.handoff.make_handoff`. Allowed tools are read-only.
   Never put parent_secret, raw headers, or the full claim row into facts.
2. `lab8.runtime.run_readonly_investigators` runs those tools.
3. The orchestrator quotes from the investigator's order view and calls
   `durability.issue_refund`. Investigators have no write registry.
   Pass the full quote; the host subtracts earlier refunds on the same order.
   `lookup_refund_history` is a read-only tool you may hand to an investigator.
4. Trace the sanitized handoff, not the parent context.

An LLM summary of the parent context is not a sanitizer. Use the allowlist.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.

Ranh giới trong shape này:

- Orchestrator (code) đọc claim qua `get_claim_view`, lập handoff bằng allowlist,
  nhận kết quả investigator, gọi `durability.issue_refund`. Chỉ orchestrator ghi.
- Investigator chỉ có tool đọc (`worker=True`), chỉ thấy handoff đã sanitize.
- Model (MockLLM) chỉ lập kế hoạch và soạn câu trả lời; không thấy ticket, không quyết tiền.
- Không có bước nào để chữ trong ticket đè dữ kiện order (khác swarm tham chiếu).
"""

from __future__ import annotations

import sqlite3

from lab8 import durability
from lab8.db import connect
from lab8.handoff import HandoffError, make_handoff
from lab8.mock_llm import complete
from lab8.runtime import ToolRejected, run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

SHAPE = "orchestrator"
INVESTIGATOR_TOOLS = ["lookup_order", "lookup_refund_history", "compute_compensation"]


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

    # 1. Orchestrator đọc claim qua view (không SELECT *, không đụng parent_secret / raw_headers).
    budget.add_tool(tool_cost())
    claim = get_claim_view(conn, claim_id)
    if not claim["found"]:
        return done("failed", 0, "unknown_claim")
    trace.add("claim", {"claim_id": claim_id, "has_order_id": bool(claim["order_id"])})
    if not claim["order_id"]:
        return done("needs_info", 0, "missing_order_id")

    # 2. Lập kế hoạch (model chỉ được biết danh sách tool, không thấy ticket).
    complete(budget, seed=seed, purpose="plan", prompt="investigate:" + ",".join(INVESTIGATOR_TOOLS))

    # 3. Handoff allowlist. facts rỗng: investigator tự đọc dữ kiện từ database.
    try:
        handoff = make_handoff(
            request_id=f"REQ-{claim_id}",
            claim_id=claim_id,
            task="investigate_claim",
            facts={},
            allowed_tools=INVESTIGATOR_TOOLS,
        )
    except HandoffError as exc:
        return done("failed", 0, f"handoff_rejected:{exc}")
    trace.add("handoff", safe_dump(handoff))

    # 4. Investigator chỉ đọc.
    try:
        investigated = run_readonly_investigators(conn, budget, handoff, principal_id=claim["principal_id"])
    except ToolRejected as exc:
        return done("failed", 0, f"tool_rejected:{exc}")
    tools = investigated["tools"]
    order_view = tools.get("lookup_order") or {}
    trace.add(
        "investigator",
        {
            "lookup_order": {k: order_view[k] for k in ("visible", "reason", "order") if k in order_view},
            "lookup_refund_history": tools.get("lookup_refund_history"),
        },
    )
    if not order_view.get("visible"):
        complete(budget, seed=seed, purpose="draft", prompt="escalated")
        return done("escalated", 0, order_view.get("reason"))

    # 5. Tiền: quote do code tính từ order row (investigator gọi compute_compensation).
    quote = tools.get("compute_compensation")
    if not quote:
        return done("failed", 0, "missing_quote")
    trace.add("quote", quote)
    proposal = int(quote["amount_vnd"])
    if proposal <= 0:
        complete(budget, seed=seed, purpose="draft", prompt="denied")
        return done("denied", 0, quote.get("reason"))

    # 6. Chỉ orchestrator ghi. Quote đầy đủ; host trừ phần đơn đã được hoàn.
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
