"""Value-weighted forward trace + backward on-ramp trace (docs/architecture.md §4.1-4.2)."""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from ..adapters.base import AdapterUnavailable, ChainAdapter, Transfer
from ..labels.index import LabelIndex
from .classify import _add_tx, apply_label, classify_behaviour
from .model import Node, TraceParams, TraceResult

Progress = Callable[[dict], Awaitable[None]] | None
# (chain, transfers into the bridge) -> {dest_chain, dest_address, dest_tx, usd_in, usd_out, ts_in, ts_out, tool} | None
BridgeResolver = Callable[[str, list[Transfer]], Awaitable[dict | None]] | None


def _until(since: datetime, days: int) -> datetime | None:
    u = since + timedelta(days=days)
    return None if u >= datetime.now(timezone.utc) else u


def continuity(usd_in: float, usd_out: float, seconds: float, confirmed: bool, dest_service: bool, cfg: dict) -> tuple[float, dict]:
    """Cross-chain continuity: is the money leaving the bridge on chain B the same money that entered on chain A?"""
    c = cfg["continuity"]
    amount = 1 - min(1.0, abs(usd_in - usd_out) / max(usd_in, usd_out, 1e-9))
    mins = abs(seconds) / 60
    full, zero = c["full_minutes"], c["zero_hours"] * 60
    time = 1.0 if mins <= full else max(0.0, 1 - (mins - full) / (zero - full))
    comps = {"amount": round(amount, 3), "time": round(time, 3), "bridge": 1.0 if confirmed else 0.0,
             "destination": 0.5 if dest_service else 1.0}
    score = sum(c[k] * v for k, v in comps.items())
    return round(score, 3), comps


async def _cross_chain(res: TraceResult, bridge: Node, txs: list[Transfer], resolver: BridgeResolver,
                       adapter_for, labels: LabelIndex, cfg: dict, queue: deque) -> None:
    if resolver is None:
        bridge.reasons.append("Cross-chain continuation not resolved (no bridge tracker configured)")
        return
    try:
        hit = await resolver(bridge.chain, txs)
    except AdapterUnavailable as e:
        hit = None
        res.notes.append(f"bridge lookup: {e}")
    if not hit:
        bridge.reasons.append("Bridge tracker found no matching destination transaction: trail paused here")
        return
    score, comps = continuity(hit["usd_in"], hit["usd_out"], (hit["ts_out"] - hit["ts_in"]).total_seconds(),
                              True, False, cfg)
    bridge.stats.update({"continuity": score, "continuity_components": comps, "dest_chain": hit["dest_chain"],
                         "dest_tx": hit["dest_tx"], "bridge_tool": hit.get("tool")})
    bridge.reasons.append(
        f"Cross-chain continuity {score:.2f}: ${hit['usd_in']:,.0f} in on {bridge.chain} -> ${hit['usd_out']:,.0f} out on "
        f"{hit['dest_chain']} after {abs((hit['ts_out'] - hit['ts_in']).total_seconds()) / 60:.0f} min"
        + (f" via {hit['tool']}" if hit.get("tool") else ""))
    try:
        adapter_for(hit["dest_chain"])
    except AdapterUnavailable:
        res.notes.append(f"Destination chain {hit['dest_chain']} not supported; trail stops at the bridge")
        return
    dest, new = res.node(hit["dest_chain"], hit["dest_address"], bridge.depth + 1)
    dest.value_share += bridge.value_share
    dest.arrival = hit["ts_out"] if dest.arrival is None else min(dest.arrival, hit["ts_out"])
    if bridge.value_share >= dest.parent_share:
        dest.parent, dest.parent_share, dest.parent_txs = bridge.id, bridge.value_share, [hit["dest_tx"]]
    e = res.xedge(bridge.chain, bridge.address, hit["dest_chain"], hit["dest_address"], "bridge")
    e.assets.add(hit.get("asset") or "bridged")
    e.amount_usd += hit["usd_out"]
    e.tx_count += 1
    e.tx_hashes.append(hit["dest_tx"])
    e.first_ts = hit["ts_out"]
    e.value_share += bridge.value_share
    if new:
        apply_label(dest, labels)
        if not dest.terminal:
            queue.append(dest)


async def trace(seeds: list[tuple[str, str]], fraud_time: datetime, params: TraceParams, labels: LabelIndex,
                adapter_for: Callable[[str], ChainAdapter], cfg: dict, progress: Progress = None,
                bridge_resolver: BridgeResolver = None) -> TraceResult:
    res = TraceResult()
    queue: deque[Node] = deque()
    for chain, addr in seeds:
        n, _ = res.node(chain, addr, 0)
        n.kind = "suspect"
        n.value_share += 1.0 / len(seeds)
        n.arrival = fraud_time
        apply_label(n, labels, is_seed=True)
        queue.append(n)

    expanded = 0
    while queue:
        n = queue.popleft()
        if n.terminal or n.depth >= params.max_depth:
            continue
        if len(res.edges) >= params.max_edges:
            res.notes.append(f"Edge limit {params.max_edges} reached; trace truncated.")
            break
        since = n.arrival or fraud_time
        try:
            outs = await adapter_for(n.chain).get_transfers(n.address, "out", since, _until(since, params.window_days))
        except AdapterUnavailable as e:
            n.reasons.append(f"Data unavailable: {e}")
            res.notes.append(f"{n.chain}: {e}")
            continue
        outs = [t for t in outs if t.to_address != n.address]
        n.stats["out_sample"] = len(outs)
        expanded += 1

        if n.depth > 0 and n.kind in ("intermediary", "sanctioned"):
            classify_behaviour(n, outs, labels, res, cfg)
            if n.terminal:
                await _progress(progress, res, n.depth, expanded)
                continue

        valid = [t for t in outs if t.amount_usd >= params.min_usd]
        total = sum(t.amount_usd for t in valid)
        if n.depth == 0:
            res.seed_out_usd += total
        if not valid:
            if n.depth > 0 and n.kind == "intermediary" and await _collection_wallet(n, adapter_for, labels, cfg, since):
                continue
            n.flags.add("holds_funds")
            n.reasons.append(f"No outflow ≥ ${params.min_usd:.0f} after funds arrived: funds may still be here")
            continue

        by_cp: dict[str, list[Transfer]] = defaultdict(list)
        for t in valid:
            by_cp[t.to_address].append(t)
        ranked = sorted(by_cp.items(), key=lambda kv: -sum(t.amount_usd for t in kv[1]))
        top = ranked[: params.fanout]
        followed = sum(sum(t.amount_usd for t in txs) for _, txs in top)
        if len(ranked) > params.fanout:
            n.stats["untraced_share"] = round(n.value_share * (1 - followed / total), 5)
            n.reasons.append(f"Followed top {params.fanout} of {len(ranked)} recipients "
                             f"({followed / total:.0%} of outflow value)")

        for cp, txs in top:
            usd = sum(t.amount_usd for t in txs)
            share = n.value_share * usd / total
            child, new = res.node(n.chain, cp, n.depth + 1)
            child.value_share += share
            first = min(t.timestamp for t in txs)
            child.arrival = first if child.arrival is None else min(child.arrival, first)
            if share > child.parent_share:
                child.parent, child.parent_share = n.id, share
                child.parent_txs = [t.tx_hash for t in sorted(txs, key=lambda t: -t.amount_usd)[:3]]
            e = res.edge(n.chain, n.address, cp, "forward")
            for t in txs:
                _add_tx(e, t)
            e.value_share += share
            if new:
                apply_label(child, labels)
                if child.kind == "bridge":
                    await _cross_chain(res, child, txs, bridge_resolver, adapter_for, labels, cfg, queue)
                elif not child.terminal:
                    queue.append(child)
        await _progress(progress, res, n.depth, expanded)

    await backward(res, seeds, fraud_time, params, labels, adapter_for)
    for n in res.nodes.values():
        n.value_usd = round(n.value_share * res.seed_out_usd, 2) if n.depth >= 0 else n.value_usd
    return res


async def backward(res: TraceResult, seeds, fraud_time, params: TraceParams, labels: LabelIndex, adapter_for) -> None:
    """Where did the suspect's funds come from? Finds on-ramp VASPs (exchange withdrawals / P2P buys)."""
    frontier = [(res.nodes[f"{c}:{a}"], fraud_time) for c, a in seeds]
    for d in range(1, params.back_depth + 1):
        nxt = []
        for n, until in frontier:
            try:
                ins = await adapter_for(n.chain).get_transfers(
                    n.address, "in", until - timedelta(days=params.window_days), until)
            except AdapterUnavailable as e:
                res.notes.append(f"{n.chain} backward: {e}")
                continue
            ins = [t for t in ins if t.from_address != n.address and t.amount_usd >= params.min_usd]
            total = sum(t.amount_usd for t in ins)
            if not total:
                continue
            by_s: dict[str, list[Transfer]] = defaultdict(list)
            for t in ins:
                by_s[t.from_address].append(t)
            base_share = n.stats.get("inflow_share", 1.0) if n.depth < 0 else 1.0
            for s, txs in sorted(by_s.items(), key=lambda kv: -sum(t.amount_usd for t in kv[1]))[: params.fanout]:
                key = f"{n.chain}:{s}"
                if key in res.nodes and res.nodes[key].depth >= 0:
                    continue  # already on the forward graph
                usd = sum(t.amount_usd for t in txs)
                node, new = res.node(n.chain, s, -d)
                node.stats["inflow_share"] = round(base_share * usd / total, 5)
                node.value_usd += usd
                node.parent, node.parent_txs = n.id, [t.tx_hash for t in txs[:3]]
                e = res.edge(n.chain, s, n.address, "backward")
                for t in txs:
                    _add_tx(e, t)
                e.value_share = node.stats["inflow_share"]
                if new:
                    apply_label(node, labels)
                    if not node.terminal:
                        nxt.append((node, min(t.timestamp for t in txs)))
        frontier = nxt


async def _collection_wallet(n: Node, adapter_for, labels: LabelIndex, cfg: dict, since: datetime) -> bool:
    """A wallet that keeps funds and receives from many unrelated senders looks like an exchange collection /
    hot wallet with no label: flag it for review instead of treating it as a private end point."""
    min_senders = cfg["service_like"].get("min_collection_senders", 20)
    try:
        ins = await adapter_for(n.chain).get_transfers(n.address, "in", since - timedelta(days=7), None)
    except AdapterUnavailable:
        return False
    senders = {t.from_address for t in ins if t.amount_usd >= 1}
    if len(senders) < min_senders:
        return False
    n.kind, n.terminal = "unknown_service", True
    n.stats["in_senders"] = len(senders)
    n.reasons.append(f"Collection-wallet pattern: receives from {len(senders)} distinct senders in its latest {len(ins)} "
                     f"inflows and does not pay out. Possible unlabelled exchange hot wallet: manual review / request")
    return True


async def _progress(cb: Progress, res: TraceResult, depth: int, expanded: int) -> None:
    if cb:
        await cb({"nodes": len(res.nodes), "edges": len(res.edges), "depth": depth, "expanded": expanded})
