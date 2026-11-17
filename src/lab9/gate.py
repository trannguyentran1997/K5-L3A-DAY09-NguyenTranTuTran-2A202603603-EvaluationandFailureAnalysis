"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _looser(new: dict, old: dict, where: str) -> list[str]:
    """Ratchet for one threshold dict: max may not rise, min may not fall, no_significant_drop may not go."""
    out = []
    for key, worse in (("max", lambda n, o: n > o), ("max_increase", lambda n, o: n > o),
                       ("min", lambda n, o: n < o)):
        if key in old:
            if key not in new:
                out.append(f"ratchet: {where} dropped '{key}'")
            elif worse(float(new[key]), float(old[key])):
                out.append(f"ratchet: {where} {key} loosened {old[key]} -> {new[key]}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append(f"ratchet: {where} dropped no_significant_drop")
    return out


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate."""
    import math

    problems: list[str] = []
    # 1. NaN / inf metric values
    for k, v in (pr.get("metrics") or {}).items():
        f = _num(v)
        if isinstance(v, float) and f is not None and not math.isfinite(f):
            problems.append(f"metric {k} is {v}")
    # 2. row count must equal items x seeds of the manifest
    man, rows = pr.get("manifest") or {}, pr.get("rows") or []
    want = int(man.get("items") or 0) * len(man.get("seeds") or [])
    if len(rows) != want:
        problems.append(f"rows {len(rows)} != items x seeds {want} (dropped or duplicated rows)")
    # 3. duplicated (item, seed) rows
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dups = sorted({k for k in keys if keys.count(k) > 1}, key=str)
    if dups:
        problems.append(f"duplicated rows {dups[:3]}")
    # 4. the (item, seed) set must equal the baseline's
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if set(keys) != base_keys:
        problems.append(f"(item, seed) set differs from baseline: "
                        f"{len(set(keys) - base_keys)} extra, {len(base_keys - set(keys))} missing")
    if list(man.get("seeds") or []) != list((base.get("manifest") or {}).get("seeds") or []):
        problems.append("seeds differ from baseline")
    # 5. crashed graders: evaluator_failures, or None on a graded spec metric
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s)")
    graded = [m["id"] for m in spec.get("metrics") or [] if any(m["id"] in r for r in rows)]
    for mid in graded:
        missing = sum(1 for r in rows if r.get(mid) is None)
        if missing:
            problems.append(f"{missing} row(s) with no value for {mid} (grader crashed?)")
    # 6. slice tags must match the baseline's for the same item
    base_tags = {r.get("item_id"): sorted(r.get("slices") or []) for r in base.get("rows") or []}
    moved = sorted({r.get("item_id") for r in rows
                    if r.get("item_id") in base_tags and sorted(r.get("slices") or []) != base_tags[r.get("item_id")]})
    if moved:
        problems.append(f"slice tags differ from baseline for {moved[:3]}")
    # 7. ratchet against the spec on main (same eval-set version only)
    if base_spec and base_spec.get("eval_set_version") == spec.get("eval_set_version"):
        new_m = {m["id"]: m for m in spec.get("metrics") or []}
        for old in base_spec.get("metrics") or []:
            new = new_m.get(old["id"])
            if new is None:
                problems.append(f"ratchet: metric {old['id']} removed")
                continue
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"ratchet: metric {old['id']} no longer blocking")
            problems += _looser(new.get("threshold") or {}, old.get("threshold") or {}, f"metric {old['id']}")
        new_s = {(s["name"], s["metric"]): s for s in spec.get("slices") or []}
        for old in base_spec.get("slices") or []:
            new = new_s.get((old["name"], old["metric"]))
            where = f"slice {old['name']}/{old['metric']}"
            if new is None:
                problems.append(f"ratchet: {where} removed")
                continue
            if old.get("blocking") and not new.get("blocking"):
                problems.append(f"ratchet: {where} no longer blocking")
            problems += _looser(new, old, where)
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, mid = s["name"], s["metric"]
        sid = f"slice:{name}/{mid}"
        a, b = per_item(pr, mid, slice_name=name), per_item(base, mid, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if s.get("no_significant_drop"):
                keys = sorted(set(a) & set(b))
                if keys:
                    d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                       n_resamples=bs.get("n_resamples", 1000),
                                                       rng=bs.get("rng", 2027))
                    note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                    if hi < 0:
                        verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
