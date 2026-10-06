"""Address classification: labels first, then behavioural rules (docs/architecture.md §4.3)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ..adapters.base import Transfer
from ..labels.index import VASP_TYPES, LabelIndex
from ..labels.risk import categories, programs_of
from .model import Node, TraceResult


def apply_label(n: Node, labels: LabelIndex, is_seed: bool = False) -> None:
    s = labels.sanctioned(n.chain, n.address)
    if s:
        n.flags.add("sanctioned")
        n.stats["sanction_entity"] = s.entity
        cats = categories(s.entity, s.ref)
        if cats:
            n.stats["risk_categories"] = cats
            for c in cats:
                n.flags.add(f"risk:{c['code']}")
        progs = programs_of(s.ref)
        n.reasons.append(f"On OFAC SDN sanctions list: {s.entity}"
                         + (f" (programs {', '.join(progs)})" if progs else f" ({s.source})")
                         + (f" -> {', '.join(c['label'] for c in cats)}" if cats else ""))
        if not is_seed and n.kind == "intermediary":
            n.kind = "sanctioned"
    lab = labels.primary(n.chain, n.address)
    if lab is None:
        return
    if is_seed:
        n.reasons.append(f"Seed wallet carries label: {lab.entity} ({lab.type}, {lab.source})")
        return
    n.entity, n.label_source, n.label_tier = lab.entity, lab.source, lab.tier
    if lab.type == "mixer":
        n.kind, n.terminal = "mixer", True
        n.reasons.append(f"Known mixer: {lab.entity} ({lab.source}). Trace stops; no attribution through mixers.")
    elif lab.type == "bridge":
        n.kind, n.terminal = "bridge", True
        n.reasons.append(f"Cross-chain bridge: {lab.entity} ({lab.source}). Cross-chain follow-up needed.")
    elif lab.type == "swap_service":
        n.kind, n.terminal = "swap_service", True
        n.reasons.append(f"Cross-chain swap service: {lab.entity} ({lab.source}). Cross-chain follow-up needed.")
    elif lab.type in VASP_TYPES:
        n.kind, n.terminal = lab.type, True
        n.reasons.append(f"Labelled {lab.entity} {lab.type.replace('vasp_', '')} wallet ({lab.source}, {lab.tier})")
    elif lab.type == "offramp":
        n.kind, n.terminal = "offramp", True
        n.reasons.append(f"Known P2P / fintech off-ramp: {lab.entity} ({lab.source})")


def classify_behaviour(n: Node, outs: list[Transfer], labels: LabelIndex, res: TraceResult, cfg: dict) -> None:
    """Deposit-sweep and service-like rules for an unlabelled node, using its outgoing transfers."""
    usd_out = sum(t.amount_usd for t in outs)
    if usd_out <= 0:
        return
    by_cp: dict[str, list[Transfer]] = defaultdict(list)
    for t in outs:
        by_cp[t.to_address].append(t)
    n.stats["out_counterparties"] = len(by_cp)

    # --- deposit-sweep (by exchange: one deposit address may sweep into several hot wallets of the same VASP) ---
    ds = cfg["deposit_sweep"]
    ent_txs: dict[str, list[Transfer]] = defaultdict(list)
    ent_lab: dict[str, tuple[str, object]] = {}
    for cp, txs in by_cp.items():
        lab = labels.primary(n.chain, cp)
        if lab and lab.type in ("vasp_hot", "vasp_cold"):
            ent_txs[lab.entity] += txs
            if lab.entity not in ent_lab or sum(t.amount_usd for t in txs) > \
                    sum(t.amount_usd for t in by_cp[ent_lab[lab.entity][0]]):
                ent_lab[lab.entity] = (cp, lab)  # the entity's largest receiving wallet represents it
    top_ent = max(ent_txs, key=lambda e: sum(t.amount_usd for t in ent_txs[e]), default=None)
    top_cp, top_lab = ent_lab[top_ent] if top_ent else (None, None)
    top_txs = ent_txs[top_ent] if top_ent else []
    top_share = sum(t.amount_usd for t in top_txs) / usd_out
    if top_lab and top_share >= ds["min_out_share"] and len(by_cp) <= ds["max_out_counterparties"]:
        # delay from the traced funds' arrival to the first sweep (later sweeps belong to later deposits)
        delays = [(t.timestamp - n.arrival).total_seconds() / 3600 for t in top_txs if n.arrival and t.timestamp >= n.arrival]
        first = min(delays) if delays else None
        if first is not None and first <= ds["max_sweep_delay_hours"]:
            n.kind, n.terminal = "vasp_deposit", True
            n.entity, n.label_source, n.label_tier = top_lab.entity, "heuristic:deposit_sweep", "inferred"
            n.sweep_to, n.sweep_share = top_cp, top_share
            hots = [cp for cp in by_cp if (lb := labels.primary(n.chain, cp))
                    and lb.type in ("vasp_hot", "vasp_cold") and lb.entity == top_lab.entity]
            n.reasons.append(
                f"Deposit-sweep pattern: {top_share:.0%} of outflow swept to {top_lab.entity} hot wallet"
                + (f" {short(top_cp)}" if len(hots) == 1 else f"s ({len(hots)} addresses, largest {short(top_cp)})")
                + f" ({top_lab.source}), {len(by_cp)} counterpart{'y' if len(by_cp) == 1 else 'ies'}, "
                f"swept {_fmt_delay(first)} after the funds arrived")
            for cp in hots:
                lab = labels.primary(n.chain, cp)
                hot, _ = res.node(n.chain, cp, n.depth + 1)
                hot.kind, hot.terminal = lab.type, True
                hot.entity, hot.label_source, hot.label_tier = lab.entity, lab.source, lab.tier
                hot.flags.add("sweep_target")
                if not hot.reasons:
                    hot.reasons.append(f"Labelled {lab.entity} hot wallet ({lab.source}, {lab.tier})")
                e = res.edge(n.chain, n.address, cp, "sweep")
                for t in by_cp[cp]:
                    _add_tx(e, t)
                e.value_share = n.value_share * sum(t.amount_usd for t in by_cp[cp]) / usd_out
                hot.value_share = max(hot.value_share, e.value_share)
                if hot.parent is None:
                    hot.parent, hot.parent_share, hot.parent_txs = n.id, e.value_share, e.tx_hashes[:3]
            return

    # --- exchange cluster: most outflow goes to ONE exchange's labelled wallets (internal / consolidation wallet) ---
    ec = cfg.get("exchange_cluster")
    if ec and len(by_cp) > ds["max_out_counterparties"]:
        by_entity: dict[str, float] = defaultdict(float)
        best_cp: dict[str, tuple[str, float]] = {}
        for cp, txs in by_cp.items():
            lab = labels.primary(n.chain, cp)
            if lab and lab.type in ("vasp_hot", "vasp_cold"):
                usd = sum(t.amount_usd for t in txs)
                by_entity[lab.entity] += usd
                if usd > best_cp.get(lab.entity, ("", 0.0))[1]:
                    best_cp[lab.entity] = (cp, usd)
        if by_entity:
            entity, usd = max(by_entity.items(), key=lambda kv: kv[1])
            share = usd / usd_out
            if share >= ec["min_out_share"]:
                n.kind, n.terminal = "vasp_hot", True
                n.entity, n.label_source, n.label_tier = entity, "heuristic:exchange_cluster", "inferred"
                n.sweep_to, n.sweep_share = best_cp[entity][0], share
                n.reasons.append(
                    f"Exchange-cluster pattern: {share:.0%} of outflow goes to {entity} labelled wallets "
                    f"(largest: {short(best_cp[entity][0])}) across {len(by_cp)} counterparties. Unlabelled "
                    f"{entity} internal wallet (candidate cluster similarity, not a confirmed label)")
                return

    # --- service-like (high-throughput wallet, possibly an unlabelled VASP) ---
    sl = cfg["service_like"]
    span_days = (outs[-1].timestamp - outs[0].timestamp).total_seconds() / 86400 if len(outs) > 1 else 999
    if len(by_cp) >= sl["min_sample_counterparties"] or (len(outs) >= 200 and abs(span_days) <= sl["full_page_within_days"]):
        n.kind, n.terminal = "unknown_service", True
        n.reasons.append(
            f"Service-like behaviour: {len(by_cp)} distinct recipients in latest {len(outs)} transfers. "
            f"Possible unlabelled VASP or payment service: manual review")


def _add_tx(e, t: Transfer) -> None:
    e.assets.add(t.asset)
    e.amount_usd += t.amount_usd
    e.tx_count += 1
    if len(e.tx_hashes) < 20:
        e.tx_hashes.append(t.tx_hash)
    if e.first_ts is None or t.timestamp < e.first_ts:
        e.first_ts, e.block = t.timestamp, t.block


def _fmt_delay(hours: float) -> str:
    if hours < 1 / 60:
        return f"{hours * 3600:.0f} s"
    if hours < 1:
        return f"{hours * 60:.0f} min"
    return f"{hours:.1f} h"


def short(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}" if len(a) > 12 else a


__all__ = ["apply_label", "classify_behaviour", "short", "timedelta"]
