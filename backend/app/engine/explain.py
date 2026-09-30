"""Explainable scoring: split a noisy-OR confidence into additive factor points, and compute what-if scenarios.

Confidence C = pf * (1 - prod(1 - t_i)), t_i = w_i * s_i. Taking logs, -ln(1 - raw) = sum(-ln(1 - t_i)), so each
factor's share of the evidence is -ln(1 - t_i) / sum. Points_i = C * share_i * 100, which sum exactly to C * 100.
Nothing here is estimated: every number is recomputed from the stored signals and weights.
"""
from __future__ import annotations

import math

FACTOR_LABELS = {
    "label_tier": "Label evidence",
    "sweep": "Deposit-sweep / cluster behaviour",
    "ext_tag": "External explorer tag",
    "history": "Historical relationship",
    "value": "Value convergence",
    "recency": "Timing",
}


def _terms(signals: dict, weights: dict) -> dict[str, float]:
    out = {}
    for k in weights:
        s = signals.get(k)
        if s is None:
            continue
        t = min(0.999, weights[k] * max(0.0, min(1.0, float(s))))
        if t > 0:
            out[k] = t
    return out


def confidence(signals: dict, weights: dict, path_factor: float) -> float:
    p = 1.0
    for t in _terms(signals, weights).values():
        p *= 1 - t
    return round(path_factor * (1 - p), 4)


def contributions(signals: dict, weights: dict, path_factor: float) -> list[dict]:
    terms = _terms(signals, weights)
    conf = confidence(signals, weights, path_factor)
    logs = {k: -math.log(1 - t) for k, t in terms.items()}
    total = sum(logs.values()) or 1.0
    rows = [{"factor": k, "label": FACTOR_LABELS.get(k, k), "signal": round(float(signals[k]), 4),
             "weight": weights[k], "points": round(conf * logs[k] / total * 100, 1)} for k in terms]
    return sorted(rows, key=lambda r: -r["points"])


def what_if(signals: dict, weights: dict, path_factor: float, cfg: dict) -> list[dict]:
    """Deterministic scenarios: how the confidence would move if one piece of evidence changed."""
    base = confidence(signals, weights, path_factor)
    scenarios = [
        ("The VASP confirms this address via Sahyog", {**signals, "label_tier": 1.0, "history": 1.0}, path_factor),
        ("The address shows up in another case for the same VASP", {**signals, "history": max(0.8, signals.get("history") or 0)}, path_factor),
        ("A bridge with unknown continuity is found on the path", signals, path_factor * cfg["path_factor"]["bridge"]),
        ("A mixer is found on the path", signals, 0.0),
    ]
    out = []
    for text, sig, pf in scenarios:
        c = confidence(sig, weights, pf)
        if abs(c - base) >= 0.005:
            out.append({"scenario": text, "confidence": c, "delta": round(c - base, 4)})
    return out


def compare(a: dict, b: dict) -> list[dict]:
    """Factor-by-factor gap between two candidates' contribution lists (a minus b), largest first."""
    pa = {r["factor"]: r for r in a}
    pb = {r["factor"]: r for r in b}
    rows = []
    for k in set(pa) | set(pb):
        va, vb = pa.get(k, {}).get("points", 0.0), pb.get(k, {}).get("points", 0.0)
        rows.append({"factor": k, "label": FACTOR_LABELS.get(k, k), "a": va, "b": vb, "gap": round(va - vb, 1)})
    return sorted(rows, key=lambda r: -abs(r["gap"]))
