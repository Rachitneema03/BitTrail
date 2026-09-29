"""Address classification: labels first, then behavioural rules (docs/architecture.md §4.3)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from ..adapters.base import Transfer
from ..labels.index import VASP_TYPES, LabelIndex
from .model import Node, TraceResult


def apply_label(n: Node, labels: LabelIndex, is_seed: bool = False) -> None:
    s = labels.sanctioned(n.chain, n.address)
    if s:
        n.flags.add("sanctioned")
        n.reasons.append(f"On OFAC SDN sanctions list ({s.source})")
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

    # --- deposit-sweep ---
    ds = cfg["deposit_sweep"]
    top_cp, top_txs = max(by_cp.items(), key=lambda kv: sum(t.amount_usd for t in kv[1]))
    top_share = sum(t.amount_usd for t in top_txs) / usd_out
    top_lab = labels.primary(n.chain, top_cp)
    if top_lab and top_lab.type in ("vasp_hot", "vasp_cold") and top_share >= ds["min_out_share"] \
            and len(by_cp) <= ds["max_out_counterparties"]:
        # delay from the traced funds' arrival to the first sweep (later sweeps belong to later deposits)
        delays = [(t.timestamp - n.arrival).total_seconds() / 3600 for t in top_txs if n.arrival and t.timestamp >= n.arrival]
        first = min(delays) if delays else None
        if first is not None and first <= ds["max_sweep_delay_hours"]:
            n.kind, n.terminal = "vasp_deposit", True
            n.entity, n.label_source, n.label_tier = top_lab.entity, "heuristic:deposit_sweep", "inferred"
            n.sweep_to, n.sweep_share = top_cp, top_share
            n.reasons.append(
                f"Deposit-sweep pattern: {top_share:.0%} of outflow swept to {top_lab.entity} hot wallet "
                f"{short(top_cp)} ({top_lab.source}), {len(by_cp)} counterpart{'y' if len(by_cp) == 1 else 'ies'}, "
                f"swept {_fmt_delay(first)} after the funds arrived")
            hot, _ = res.node(n.chain, top_cp, n.depth + 1)
            hot.kind, hot.terminal = top_lab.type, True
            hot.entity, hot.label_source, hot.label_tier = top_lab.entity, top_lab.source, top_lab.tier
            hot.flags.add("sweep_target")
            if not hot.reasons:
                hot.reasons.append(f"Labelled {top_lab.entity} hot wallet ({top_lab.source}, {top_lab.tier})")
            e = res.edge(n.chain, n.address, top_cp, "sweep")
            for t in top_txs:
                _add_tx(e, t)
            e.value_share = n.value_share * top_share
            hot.value_share = max(hot.value_share, e.value_share)
            if hot.parent is None:
                hot.parent, hot.parent_share, hot.parent_txs = n.id, e.value_share, e.tx_hashes[:3]
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
