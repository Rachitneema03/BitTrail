"""Value-weighted forward trace + backward on-ramp trace across chains (docs/architecture.md §4.1-4.2).

Forward trace, breadth-first, one level at a time (each level's transfers are fetched concurrently):
- seeds are weighted by how much they sent after the fraud; an EVM seed is also traced on every other EVM chain
  where the same address is active (one key pair, many chains)
- adaptive dust filter: ignore transfers below max(TRACE_MIN_USD, dust share x value reaching the wallet)
- fan-out: follow the top-N recipients by USD, value split proportionally
- cross-chain: when funds enter a bridge / swap service, or vanish into a service-like wallet, public trackers are
  asked where that deposit came out; the trail continues on the destination chain with a continuity score
- equal-output CoinJoin transactions (Bitcoin) are treated as mixers: the trail stops there
"""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from ..adapters.base import EVM_CHAINS, AdapterUnavailable, ChainAdapter, Transfer
from ..labels.index import LabelIndex
from .classify import _add_tx, apply_label, classify_behaviour, short
from .model import Node, TraceParams, TraceResult

Progress = Callable[[dict], Awaitable[None]] | None
# (chain, transfers into the bridge) -> hits [{dest_chain, dest_address, dest_tx, usd_in, usd_out, ts_in, ts_out, tool, ...}]
BridgeResolver = Callable[[str, list[Transfer]], Awaitable[list[dict] | dict | None]] | None
# (source chain, depositor address, deposit transfer) -> unconfirmed hit or None
FallbackMatcher = Callable[[str, str, Transfer], Awaitable[dict | None]] | None
CROSS_KINDS = ("bridge", "swap_service")


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


class _Ctx:
    """Everything one trace run needs, so the helpers stay small."""

    def __init__(self, res: TraceResult, params: TraceParams, labels: LabelIndex, adapter_for, cfg: dict,
                 queue: deque, resolver: BridgeResolver, fallback: FallbackMatcher):
        self.res, self.params, self.labels, self.adapter_for, self.cfg = res, params, labels, adapter_for, cfg
        self.queue, self.resolver, self.fallback = queue, resolver, fallback
        self.incoming: dict[str, list[tuple[str, Transfer]]] = defaultdict(list)  # node id -> (sender, transfer)
        self.outs: dict[str, list[Transfer]] = {}


async def _fetch_out(ctx: _Ctx, n: Node, fraud_time: datetime) -> list[Transfer] | None:
    if n.id in ctx.outs:
        return ctx.outs[n.id]
    since = n.arrival or fraud_time
    try:
        outs = await ctx.adapter_for(n.chain).get_transfers(n.address, "out", since, _until(since, ctx.params.window_days))
    except AdapterUnavailable as e:
        n.reasons.append(f"Data unavailable: {e}")
        ctx.res.notes.append(f"{n.chain}: {e}")
        return None
    ctx.outs[n.id] = [t for t in outs if t.to_address != n.address]
    return ctx.outs[n.id]


async def _prefetch(ctx: _Ctx, nodes: list[Node], fraud_time: datetime) -> None:
    """Fetch one BFS level concurrently (providers rate-limit themselves; different chains run in parallel)."""
    todo = [n for n in nodes if not n.terminal and n.id not in ctx.outs and n.depth < ctx.params.max_depth]
    if todo:
        await asyncio.gather(*(_fetch_out(ctx, n, fraud_time) for n in todo))


async def _probe(ctx: _Ctx, child: Node, fraud_time: datetime) -> None:
    """Proactive bridge check for a new, unlabelled recipient: is the deposit INTO it a known bridge / swap
    transaction? Bridge vaults (THORChain), deposit addresses (Layerswap) and routers often look like ordinary
    wallets, and following their outflow would follow other people's money."""
    p = ctx.cfg.get("crosschain_probe", {})
    if child.value_share >= p.get("min_share", 0.01) and await _cross_chain(ctx, child, fraud_time):
        return
    if not child.terminal:
        ctx.queue.append(child)


async def _expand_seeds(seeds: list[tuple[str, str]], fraud_time: datetime, adapter_for, notes: list[str]) -> list[tuple[str, str]]:
    """An EVM address is the same key on Ethereum, Polygon and BNB Chain: trace it wherever it is active."""
    out = list(seeds)
    for chain, addr in seeds:
        if chain not in EVM_CHAINS:
            continue
        for other in EVM_CHAINS:
            if other == chain or (other, addr) in out:
                continue
            try:
                ad = adapter_for(other)
            except AdapterUnavailable:
                continue
            probe = getattr(ad, "has_activity", None)
            if probe and await probe(addr, fraud_time):
                out.append((other, addr))
                notes.append(f"Multi-chain: the suspect address {short(addr)} is also active on {other} after the fraud; "
                             f"traced there too")
    return out


def _dust_floor(ctx: _Ctx, n: Node, outs: list[Transfer], inflow_usd: float) -> tuple[float, list[Transfer], str | None]:
    """Adaptive dust filter. Returns (floor, kept transfers, explanation)."""
    d = ctx.cfg.get("dust", {})
    base = ctx.params.min_usd
    floor = base
    if d.get("adaptive", True) and inflow_usd > 0:
        floor = min(d.get("max_floor_usd", 1000.0), max(base, d.get("relative_share", 0.005) * inflow_usd))
    kept = [t for t in outs if t.amount_usd >= floor]
    dropped = [t for t in outs if t.amount_usd < floor]
    total = sum(t.amount_usd for t in outs) or 1.0
    dropped_usd = sum(t.amount_usd for t in dropped)
    poisoning = sum(1 for t in dropped if t.amount_usd < d.get("poisoning_usd", 1.0))
    # many small transfers carrying real value is structuring, not dust: fall back to the absolute floor
    if floor > base and dropped_usd / total >= d.get("structuring_share", 0.2):
        kept = [t for t in outs if t.amount_usd >= base]
        n.flags.add("structuring")
        return base, kept, (f"Many small transfers carry {dropped_usd / total:.0%} of the outflow (possible structuring): "
                            f"dust floor kept at ${base:,.0f}")
    if not dropped:
        return floor, kept, None
    ctx.res.dust["transfers"] += len(dropped)
    ctx.res.dust["usd"] += dropped_usd
    ctx.res.dust["poisoning"] += poisoning
    n.stats.update({"dust_floor_usd": round(floor, 2), "dust_filtered": len(dropped), "dust_filtered_usd": round(dropped_usd, 2)})
    why = (f"Adaptive dust filter: ignored {len(dropped)} transfer{'s' if len(dropped) != 1 else ''} "
           f"(${dropped_usd:,.2f}) below ${floor:,.2f}"
           + (f" = {d.get('relative_share', 0.005):.1%} of the ${inflow_usd:,.0f} reaching this wallet" if floor > base else "")
           + (f"; {poisoning} look like address-poisoning dust" if poisoning else ""))
    return floor, kept, why


def _coinjoin(ctx: _Ctx, n: Node, transfers: list[Transfer]) -> list[Transfer]:
    """Split off transfers spent through an equal-output CoinJoin: a mixer node per transaction, the trail stops."""
    cj = [t for t in transfers if "coinjoin" in t.tags]
    if not cj:
        return transfers
    by_tx: dict[str, list[Transfer]] = defaultdict(list)
    for t in cj:
        by_tx[t.tx_hash].append(t)
    for txid, ts in by_tx.items():
        m, new = ctx.res.node(n.chain, f"coinjoin:{txid}", n.depth + 1)
        share = n.value_share * sum(t.amount_usd for t in ts) / max(sum(t.amount_usd for t in transfers), 1e-9)
        m.value_share += share
        if new:
            m.kind, m.terminal, m.entity = "mixer", True, "CoinJoin"
            m.label_source, m.label_tier = "heuristic:coinjoin", "inferred"
            m.parent, m.parent_share, m.parent_txs = n.id, share, [txid]
            m.reasons.append(f"Equal-output CoinJoin transaction {short(txid)}: inputs from many owners, identical "
                             f"outputs, so output ownership cannot be determined. Trace stops (no attribution through mixers).")
        e = ctx.res.edge(n.chain, n.address, m.address, "mix")
        for t in ts:
            _add_tx(e, t)
        e.value_share += share
    return [t for t in transfers if "coinjoin" not in t.tags]


async def _cross_chain(ctx: _Ctx, b: Node, fraud_time: datetime) -> bool:
    """Funds entered `b` (a bridge / swap service, labelled or behaviour-detected). Ask the trackers where they came out.
    Returns True when at least one destination was found."""
    deposits = ctx.incoming.get(b.id, [])
    if not deposits:
        return False
    if ctx.resolver is None and ctx.fallback is None:
        b.reasons.append("Cross-chain continuation not resolved (no bridge tracker configured)")
        return False
    hits: list[dict] = []
    if ctx.resolver is not None:
        try:
            r = await ctx.resolver(b.chain, [t for _, t in deposits])
            hits = [r] if isinstance(r, dict) else list(r or [])
        except AdapterUnavailable as e:
            ctx.res.notes.append(f"bridge lookup: {e}")
    # the unconfirmed same-address match is only tried for wallets already known to be bridges: for an arbitrary
    # service wallet a coincidental arrival elsewhere would be a false cross-chain link
    if not hits and ctx.fallback is not None and b.kind in CROSS_KINDS:
        for sender, t in sorted(deposits, key=lambda st: -st[1].amount_usd)[:2]:
            h = await ctx.fallback(b.chain, sender, t)
            if h:
                hits.append(h)
                break
    if not hits:
        if b.kind in CROSS_KINDS:
            b.reasons.append("No bridge tracker knows this deposit and no matching arrival was found: trail paused here")
        return False

    in_usd = sum(t.amount_usd for _, t in deposits) or 1.0
    confirmed_any = any(h.get("confirmed", True) for h in hits)
    if b.kind not in CROSS_KINDS:  # behaviour-detected: the tracker tells us what this wallet is
        h0 = hits[0]
        b.kind = "swap_service" if h0.get("kind") == "swap" else "bridge"
        b.entity = b.entity or h0.get("entity")
        b.label_source = f"bridge_tracker:{h0.get('provider')}" if confirmed_any else "heuristic:same_address"
        b.label_tier = "published" if confirmed_any else "inferred"
        b.flags.discard("holds_funds")
        b.reasons.append(f"{b.entity} deposit address / contract (identified by {h0.get('provider')} from the deposit "
                         f"transaction, not by a static label)")
    b.terminal = True
    hops = []
    for h in hits:
        secs = (h["ts_out"] - h["ts_in"]).total_seconds()
        try:
            ctx.adapter_for(h["dest_chain"])
            supported = True
        except AdapterUnavailable:
            supported = False
        dest, new = ctx.res.node(h["dest_chain"], h["dest_address"], b.depth + 1)
        if new:
            apply_label(dest, ctx.labels)
        score, comps = continuity(h["usd_in"], h["usd_out"], secs, h.get("confirmed", True),
                                  dest.kind == "unknown_service", ctx.cfg)
        share = b.value_share * min(1.0, h["usd_in"] / in_usd)
        dest.value_share += share
        dest.arrival = h["ts_out"] if dest.arrival is None else min(dest.arrival, h["ts_out"])
        if share >= dest.parent_share:
            dest.parent, dest.parent_share, dest.parent_txs = b.id, share, [h["dest_tx"]]
        e = ctx.res.xedge(b.chain, b.address, h["dest_chain"], h["dest_address"], "bridge")
        e.assets.add(h.get("asset") or "bridged")
        e.amount_usd += h["usd_out"]
        e.tx_count += 1
        e.tx_hashes.append(h["dest_tx"])
        e.first_ts = h["ts_out"] if e.first_ts is None else min(e.first_ts, h["ts_out"])
        e.value_share += share
        hop = {"provider": h.get("provider"), "tool": h.get("tool"), "entity": b.entity, "from_chain": b.chain,
               "bridge_address": b.address, "src_tx": h.get("src_tx"), "to_chain": h["dest_chain"],
               "to_address": h["dest_address"], "dest_tx": h["dest_tx"], "usd_in": round(h["usd_in"], 2),
               "usd_out": round(h["usd_out"], 2), "minutes": round(abs(secs) / 60, 1), "continuity": score,
               "components": comps, "confirmed": h.get("confirmed", True), "value_share": round(share, 5),
               "asset": h.get("asset"), "supported": supported, "ts_in": h["ts_in"].isoformat(),
               "ts_out": h["ts_out"].isoformat()}
        hops.append(hop)
        ctx.res.crosschain.append(hop)
        b.reasons.append(
            f"Cross-chain {'swap' if b.kind == 'swap_service' else 'bridge'} {b.chain} -> {h['dest_chain']}"
            + (f" via {h['tool']}" if h.get("tool") else "") + f": ${h['usd_in']:,.0f} in, ${h['usd_out']:,.0f} out "
            f"after {abs(secs) / 60:.0f} min, continuity {score:.2f} "
            + ("(tracker-confirmed pair of transactions)" if h.get("confirmed", True)
               else "(unconfirmed: same address, value after fee and timing match)"))
        if not supported:
            dest.terminal = True
            dest.flags.add("unsupported_chain")
            dest.reasons.append(f"Destination chain {h['dest_chain']} is outside BitTrail's adapters: trail ends here")
            ctx.res.notes.append(f"Destination chain {h['dest_chain']} not supported; trail stops at the bridge")
        elif new and not dest.terminal:
            ctx.queue.append(dest)
    b.stats.update({"continuity": min(x["continuity"] for x in hops), "crosschain": hops,
                    "dest_chain": hops[0]["to_chain"], "dest_tx": hops[0]["dest_tx"], "bridge_tool": hops[0]["tool"]})
    return True


async def trace(seeds: list[tuple[str, str]], fraud_time: datetime, params: TraceParams, labels: LabelIndex,
                adapter_for: Callable[[str], ChainAdapter], cfg: dict, progress: Progress = None,
                bridge_resolver: BridgeResolver = None, fallback: FallbackMatcher = None) -> TraceResult:
    res = TraceResult()
    queue: deque[Node] = deque()
    ctx = _Ctx(res, params, labels, adapter_for, cfg, queue, bridge_resolver, fallback)

    seeds = await _expand_seeds(seeds, fraud_time, adapter_for, res.notes)
    seed_nodes = []
    for chain, addr in seeds:
        n, _ = res.node(chain, addr, 0)
        n.kind = "suspect"
        n.arrival = fraud_time
        apply_label(n, labels, is_seed=True)
        seed_nodes.append(n)
    # weight seeds by what they sent after the fraud (equal split if nothing measurable)
    await _prefetch(ctx, seed_nodes, fraud_time)
    sent = [sum(t.amount_usd for t in (ctx.outs.get(n.id) or []) if t.amount_usd >= params.min_usd) for n in seed_nodes]
    for n, s in zip(seed_nodes, sent):
        n.value_share += s / sum(sent) if sum(sent) else 1.0 / len(seed_nodes)
        n.stats["sent_usd"] = round(s, 2)
        queue.append(n)
    res.seed_out_usd = sum(sent)

    expanded, level = 0, -1
    while queue:
        n = queue.popleft()
        if n.terminal or n.depth >= params.max_depth:
            continue
        if len(res.edges) >= params.max_edges:
            res.notes.append(f"Edge limit {params.max_edges} reached; trace truncated.")
            break
        if n.depth > level:
            level = n.depth
            await _prefetch(ctx, [n, *[q for q in queue if q.depth == level]], fraud_time)
        outs = await _fetch_out(ctx, n, fraud_time)
        if outs is None:
            continue
        n.stats["out_sample"] = len(outs)
        expanded += 1

        if n.depth > 0 and n.kind in ("intermediary", "sanctioned"):
            classify_behaviour(n, outs, labels, res, cfg)
            if n.terminal:
                if n.kind == "unknown_service":
                    await _cross_chain(ctx, n, fraud_time)
                await _progress(progress, res, n.depth, expanded)
                continue

        inflow = n.value_share * res.seed_out_usd if n.depth > 0 else n.stats.get("sent_usd", 0.0)
        floor, valid, why = _dust_floor(ctx, n, outs, inflow)
        if why:
            n.reasons.append(why)
        valid = _coinjoin(ctx, n, valid)
        total = sum(t.amount_usd for t in valid)
        if not valid:
            if n.depth > 0 and n.kind == "intermediary":
                if await _cross_chain(ctx, n, fraud_time):
                    continue
                if await _collection_wallet(n, adapter_for, labels, cfg, n.arrival or fraud_time):
                    await _cross_chain(ctx, n, fraud_time)
                    continue
            if not n.terminal:
                n.flags.add("holds_funds")
                n.reasons.append(f"No outflow ≥ ${floor:,.0f} after funds arrived: funds may still be here")
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

        fresh: list[Node] = []
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
            ctx.incoming[child.id].extend((n.address, t) for t in txs)
            e = res.edge(n.chain, n.address, cp, "forward")
            for t in txs:
                _add_tx(e, t)
            e.value_share += share
            if new:
                apply_label(child, labels)
                if child.kind in CROSS_KINDS:
                    await _cross_chain(ctx, child, fraud_time)
                elif not child.terminal:
                    fresh.append(child)
        if fresh and ctx.resolver is not None:
            await asyncio.gather(*(_probe(ctx, c, fraud_time) for c in fresh))
        else:
            queue.extend(fresh)
        await _progress(progress, res, n.depth, expanded)

    await backward(res, [(n.chain, n.address) for n in seed_nodes], fraud_time, params, labels, adapter_for)
    for n in res.nodes.values():
        n.value_usd = round(n.value_share * res.seed_out_usd, 2) if n.depth >= 0 else n.value_usd
    res.dust["usd"] = round(res.dust["usd"], 2)
    return res


async def backward(res: TraceResult, seeds, fraud_time, params: TraceParams, labels: LabelIndex, adapter_for) -> None:
    """Where did the suspect's funds come from? Finds on-ramp VASPs (exchange withdrawals / P2P buys)."""
    frontier = [(res.nodes[f"{c}:{a}"], fraud_time) for c, a in seeds]
    for d in range(1, params.back_depth + 1):
        nxt = []

        async def fetch(n, until):
            try:
                return await adapter_for(n.chain).get_transfers(n.address, "in", until - timedelta(days=params.window_days), until)
            except AdapterUnavailable as e:
                res.notes.append(f"{n.chain} backward: {e}")
                return []

        results = await asyncio.gather(*(fetch(n, u) for n, u in frontier))
        for (n, until), ins in zip(frontier, results):
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
        await cb({"nodes": len(res.nodes), "edges": len(res.edges), "depth": depth, "expanded": expanded,
                  "chains": sorted({n.chain for n in res.nodes.values()}), "bridges": len(res.crosschain)})
