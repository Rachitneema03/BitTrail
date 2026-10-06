"""Confidence, actionability and ranking of candidate VASPs (docs/architecture.md §4.4)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .classify import short
from .explain import confidence, contributions, what_if
from .model import CandidateDraft, Node, TraceResult

VASP_KINDS = {"vasp_deposit", "vasp_hot", "vasp_cold"}
# (chain, address, entity) -> (signal 0..1, reason) or None
HistoryFn = Callable[[str, str, str], tuple[float, str] | None]


def noisy_or(signals: dict[str, float], weights: dict[str, float], path_factor: float) -> float:
    return confidence(signals, weights, path_factor)


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


def path_factor(path: list[Node], cfg: dict) -> tuple[float, str]:
    if any(p.kind == "mixer" for p in path):
        return cfg["path_factor"]["mixer"], "Mixer on path: no attribution"
    bridges = [p for p in path if p.kind in ("bridge", "swap_service")]
    if not bridges:
        return cfg["path_factor"]["clean"], "Clean path: no mixer or bridge"
    pf = 1.0
    for b in bridges:
        c = b.stats.get("continuity")
        pf *= (0.5 + 0.5 * c) if c is not None else cfg["path_factor"]["bridge"]
    cs = [b.stats.get("continuity") for b in bridges if b.stats.get("continuity") is not None]
    hops = " -> ".join(dict.fromkeys(p.chain for p in path))
    why = (f"Cross-chain path {hops} via {', '.join(b.entity or 'bridge' for b in bridges)}"
           + (f": continuity {min(cs):.2f}" if cs else ": continuity unknown, confidence reduced"))
    return round(pf, 4), why


def _evidence(res: TraceResult, path: list[Node]) -> dict:
    tx = 0
    for a, b in zip(path, path[1:]):
        for d in ("forward", "sweep", "bridge"):
            e = res.edges.get((a.id, b.id, d))
            if e:
                tx += e.tx_count
    return {"transactions": tx, "intermediaries": max(0, len(path) - 2), "hops": max(0, len(path) - 1),
            "chains": list(dict.fromkeys(p.chain for p in path))}  # in path order: source chain first


def _finish(d: CandidateDraft, signals: dict, pf: float, cfg: dict, evidence: dict) -> None:
    w = cfg["weights"]
    d.explain = {"contributions": contributions(signals, w, pf), "path_factor": pf,
                 "what_if": what_if(signals, w, pf, cfg), "evidence": evidence,
                 "formula": "confidence = path_factor x (1 - prod(1 - weight_i x signal_i))"}


def score(res: TraceResult, fraud_time: datetime, cfg: dict,
          actionability_for: Callable[[str], tuple[float, str]], history_for: HistoryFn | None = None) -> list[CandidateDraft]:
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
        pf, pf_reason = path_factor(path, cfg)
        if rep.label_tier == "inferred":
            ref = res.nodes.get(f"{rep.chain}:{rep.sweep_to}")
            signals = {"label_tier": tiers.get(ref.label_tier if ref else "curated", 0.8), "sweep": rep.sweep_share or 0.0}
        else:
            signals = {"label_tier": tiers.get(rep.label_tier or "community", 0.6)}
        signals["value"] = round(min(share, 1.0), 4)
        signals["recency"] = round(recency(fraud_time, rep.arrival, cfg), 3)
        reasons = list(rep.reasons)
        if history_for:
            h = history_for(rep.chain, rep.address, entity)
            if h:
                signals["history"] = h[0]
                reasons.append(h[1])
        conf = confidence(signals, w, pf)
        act, act_reason = actionability_for(entity)
        reasons.append(f"{share:.0%} of traced value reached {entity} in {rep.depth} hop{'s' if rep.depth != 1 else ''}"
                       + (f" across {len(nodes)} addresses" if len(nodes) > 1 else ""))
        reasons.append(pf_reason)
        reasons.append(f"Route: {act_reason}")
        evidence = [tx for p in path for tx in p.parent_txs]
        d = CandidateDraft(
            vasp_name=entity, role="off_ramp", chain=rep.chain, address=rep.address, address_kind=rep.kind,
            hops=rep.depth, value_share=round(share, 4), value_usd=round(sum(x.value_usd for x in nodes), 2),
            confidence=conf, actionability=act, rank_score=round(share * conf * act, 4),
            signals={**signals, "path_factor": pf}, reasons=reasons, evidence_tx=evidence,
            path=[p.id if p.chain != rep.chain else p.address for p in path])
        _finish(d, signals, pf, cfg, _evidence(res, path))
        drafts.append(d)

    # ---- on-ramp (backward) ----
    on: dict[str, list[Node]] = {}
    for n in res.nodes.values():
        if n.depth < 0 and n.kind in VASP_KINDS and n.entity:
            on.setdefault(n.entity, []).append(n)
    for entity, nodes in on.items():
        rep = max(nodes, key=lambda x: x.stats.get("inflow_share", 0))
        share = min(1.0, sum(x.stats.get("inflow_share", 0) for x in nodes))
        signals = {"label_tier": tiers.get(rep.label_tier or "community", 0.6), "value": round(share, 4)}
        reasons = list(rep.reasons)
        if history_for:
            h = history_for(rep.chain, rep.address, entity)
            if h:
                signals["history"] = h[0]
                reasons.append(h[1])
        conf = confidence(signals, w, 1.0)
        act, act_reason = actionability_for(entity)
        reasons += [
            f"Funded the suspect wallet: {share:.0%} of its prior inflow came from {entity} ({-rep.depth} hop{'s' if rep.depth != -1 else ''} back)",
            f"The {entity} account that withdrew these funds can be identified via KYC",
            f"Route: {act_reason}"]
        path_nodes = [rep]
        p = rep
        while p.parent and p.parent in res.nodes and res.nodes[p.parent].depth <= 0:
            p = res.nodes[p.parent]
            path_nodes.append(p)
            if p.depth == 0:
                break
        d = CandidateDraft(
            vasp_name=entity, role="on_ramp", chain=rep.chain, address=rep.address, address_kind=rep.kind,
            hops=-rep.depth, value_share=round(share, 4), value_usd=round(sum(x.value_usd for x in nodes), 2),
            confidence=conf, actionability=act, rank_score=round(share * conf * act, 4),
            signals={**signals, "path_factor": 1.0}, reasons=reasons,
            evidence_tx=[tx for x in nodes for tx in x.parent_txs][:6], path=[x.address for x in path_nodes])
        ev = {"transactions": sum(len(x.parent_txs) for x in nodes), "intermediaries": max(0, len(path_nodes) - 2),
              "hops": len(path_nodes) - 1, "chains": sorted({x.chain for x in path_nodes})}
        _finish(d, signals, 1.0, cfg, ev)
        drafts.append(d)

    drafts.sort(key=lambda d: (d.role != "off_ramp", -d.rank_score))
    return drafts


__all__ = ["score", "noisy_or", "short", "path_of"]
