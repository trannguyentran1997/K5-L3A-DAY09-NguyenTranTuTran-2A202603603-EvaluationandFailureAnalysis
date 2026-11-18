"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if len(human) != len(judge):
        raise ValueError("human and judge must have the same length")
    cm = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for h, j in zip(human, judge):
        h_pos = str(h).strip().upper() == POS
        j_pos = str(j).strip().upper() == POS
        if j_pos and h_pos:
            cm["tp"] += 1          # judge bắt đúng lỗi
        elif j_pos:
            cm["fp"] += 1          # judge báo lỗi oan
        elif h_pos:
            cm["fn"] += 1          # judge bỏ sót lỗi
        else:
            cm["tn"] += 1          # cả hai cùng PASS
    return cm


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    p = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    r = cm["tp"] / (cm["tp"] + cm["fn"]) if cm["tp"] + cm["fn"] else 0.0
    return p, r


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = sum(cm.values())
    if n == 0:
        raise ValueError("kappa undefined: no rows")
    p_o = (cm["tp"] + cm["tn"]) / n                      # tỉ lệ khớp thực tế
    h_fail = (cm["tp"] + cm["fn"]) / n                   # người nói FAIL
    j_fail = (cm["tp"] + cm["fp"]) / n                   # judge nói FAIL
    p_e = h_fail * j_fail + (1 - h_fail) * (1 - j_fail)  # khớp do ngẫu nhiên
    if p_e >= 1.0:
        raise ValueError("kappa undefined: chance agreement is 1 (constant labels)")
    return (p_o - p_e) / (1 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    denom = sensitivity + specificity - 1
    if denom <= 0:
        raise ValueError("judge is no better than chance: sensitivity + specificity must exceed 1")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / denom))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy import stats as sps

    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if x.shape != y.shape:
        raise ValueError("paired bootstrap needs the same items in the same order")
    if np.array_equal(x, y):
        return (0.0, 0.0, 0.0)
    res = sps.bootstrap((x, y), lambda u, v: np.mean(u) - np.mean(v), paired=True, vectorized=False,
                        n_resamples=n_resamples, confidence_level=confidence, method="percentile",
                        rng=np.random.default_rng(rng))
    ci = res.confidence_interval
    return (float(x.mean() - y.mean()), float(ci.low), float(ci.high))


def _check_nck(n: int, c: int, k: int) -> None:
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (n, c, k)):
        raise ValueError("n, c, k must be integers")
    if n < 1 or k < 1 or c < 0 or c > n or k > n:
        raise ValueError(f"invalid (n={n}, c={c}, k={k}): need 1 <= k <= n and 0 <= c <= n")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    from math import comb

    _check_nck(n, c, k)
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    from math import comb

    _check_nck(n, c, k)
    return comb(c, k) / comb(n, k)
