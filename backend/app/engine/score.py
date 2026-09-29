"""Confidence, actionability and ranking of candidate VASPs (docs/architecture.md §4.4)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .classify import short
from .model import CandidateDraft, Node, TraceResult

VASP_KINDS = {"vasp_deposit", "vasp_hot", "vasp_cold"}


def noisy_or(signals: dict[str, float], weights: dict[str, float], path_factor: float) -> float:
    p = 1.0
    for k, s in signals.items():
        if k in weights and s is not None:
            p *= 1 - weights[k] * max(0.0, min(1.0, s))
    return round(path_factor * (1 - p), 4)


def recency(fraud_time: datetime, arrival: datetime | None, cfg: dict) -> float:
    if arrival is None:
        return 0.0
    days = (arrival - fraud_time).total_seconds() / 86400
    full, zero = cfg["recency"]["full_days"], cfg["recency"]["zero_days"]
    if days <= full:
        return 1.0
    return max(0.0, 1 - (days - full) / (zero - full))


def path_of(res: TraceResult, n: Node) -> list[Node]:
    path, seen = [n], {n.id}
    while path[-1].parent and path[-1].parent not in seen:
        p = res.nodes.get(path[-1].parent)
        if p is None:
            break
        seen.add(p.id)
        path.append(p)
    return list(reversed(path))


def score(res: TraceResult, fraud_time: datetime, cfg: dict,
          actionability_for: Callable[[str], tuple[float, str]]) -> list[CandidateDraft]:
    w, tiers = cfg["weights"], cfg["label_tier_score"]
    drafts: list[CandidateDraft] = []

    # ---- off-ramp (forward) ----
    groups: dict[str, list[Node]] = {}
    for n in res.nodes.values():
        if n.depth > 0 and n.kind in VASP_KINDS and n.entity and "sweep_target" not in n.flags:
            groups.setdefault(n.entity, []).append(n)
    for entity, nodes in groups.items():
        rep = max(nodes, key=lambda x: (x.kind == "vasp_deposit", x.value_share))
        share = sum(x.value_share for x in nodes)
        path = path_of(res, rep)
        pf_key = "bridge" if any(p.kind == "bridge" for p in path) else "clean"
        pf = cfg["path_factor"][pf_key]
        if rep.label_tier == "inferred":
            hot = res.nodes.get(f"{rep.chain}:{rep.sweep_to}")
            label_score = tiers.get(hot.label_tier if hot else "curated", 0.8)
            signals = {"label_tier": label_score, "sweep": rep.sweep_share or 0.0}
        else:
            signals = {"label_tier": tiers.get(rep.label_tier or "community", 0.6)}
        signals["value"] = round(min(share, 1.0), 4)
        signals["recency"] = round(recency(fraud_time, rep.arrival, cfg), 3)
        conf = noisy_or(signals, w, pf)
        act, act_reason = actionability_for(entity)
        reasons = list(rep.reasons)
        reasons.append(f"{share:.0%} of traced value reached {entity} in {rep.depth} hop{'s' if rep.depth != 1 else ''}"
                       + (f" across {len(nodes)} addresses" if len(nodes) > 1 else ""))
        reasons.append("Clean path: no mixer or bridge" if pf_key == "clean" else "Bridge on path: confidence reduced")
        reasons.append(f"Route: {act_reason}")
        evidence = [tx for p in path for tx in p.parent_txs]
        drafts.append(CandidateDraft(
            vasp_name=entity, role="off_ramp", chain=rep.chain, address=rep.address, address_kind=rep.kind,
            hops=rep.depth, value_share=round(share, 4), value_usd=round(sum(x.value_usd for x in nodes), 2),
            confidence=conf, actionability=act, rank_score=round(share * conf * act, 4),
            signals={**signals, "path_factor": pf}, reasons=reasons, evidence_tx=evidence,
            path=[p.address for p in path]))

    # ---- on-ramp (backward) ----
    on: dict[str, list[Node]] = {}
    for n in res.nodes.values():
        if n.depth < 0 and n.kind in VASP_KINDS and n.entity:
            on.setdefault(n.entity, []).append(n)
    for entity, nodes in on.items():
        rep = max(nodes, key=lambda x: x.stats.get("inflow_share", 0))
        share = min(1.0, sum(x.stats.get("inflow_share", 0) for x in nodes))
        signals = {"label_tier": tiers.get(rep.label_tier or "community", 0.6), "value": round(share, 4)}
        conf = noisy_or(signals, w, 1.0)
        act, act_reason = actionability_for(entity)
        reasons = list(rep.reasons) + [
            f"Funded the suspect wallet: {share:.0%} of its prior inflow came from {entity} ({-rep.depth} hop{'s' if rep.depth != -1 else ''} back)",
            f"The {entity} account that withdrew these funds can be identified via KYC",
            f"Route: {act_reason}"]
        path = [rep.address]
        p = rep
        while p.parent and p.parent in res.nodes and res.nodes[p.parent].depth <= 0:
            p = res.nodes[p.parent]
            path.append(p.address)
            if p.depth == 0:
                break
        drafts.append(CandidateDraft(
            vasp_name=entity, role="on_ramp", chain=rep.chain, address=rep.address, address_kind=rep.kind,
            hops=-rep.depth, value_share=round(share, 4), value_usd=round(sum(x.value_usd for x in nodes), 2),
            confidence=conf, actionability=act, rank_score=round(share * conf * act, 4),
            signals={**signals, "path_factor": 1.0}, reasons=reasons,
            evidence_tx=[tx for x in nodes for tx in x.parent_txs][:6], path=path))

    drafts.sort(key=lambda d: (d.role != "off_ramp", -d.rank_score))
    return drafts


__all__ = ["score", "noisy_or", "short"]
