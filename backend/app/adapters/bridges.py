"""Cross-chain destination lookup: which chain / address did a bridge or swap deposit come out on?

Every lookup is by the SOURCE transaction hash and goes through the cache. Public trackers (no keys):
- LI.FI status API        tron, bitcoin, ethereum, polygon, bsc, solana (+ the bridges LI.FI routes through)
- THORChain Midgard       native cross-chain swaps (BTC <-> ETH / BSC / ...), the classic BTC laundering route
- deBridge DLN            EVM <-> Solana order-based bridge
- Wormholescan            Wormhole token transfers (Solana <-> EVM)
A hit says the tracker confirmed both legs (`confirmed=True`). When no tracker knows the transaction,
`same_address_match` looks for the same funds arriving at the same EVM address on another EVM chain
(value after fee + time window) and returns an unconfirmed, lower-continuity hit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from ..config import settings
from .base import EVM_CHAINS, AdapterUnavailable, Transfer
from .http import cached_get
from .prices import usd_price

LIFI_STATUS = "https://li.quest/v1/status"
LIFI_CHAINS = {1: "ethereum", 137: "polygon", 56: "bsc", 1151111081099710: "solana", 20000000000001: "bitcoin",
               728126428: "tron"}
MIDGARD_CHAINS = {"BTC": "bitcoin", "ETH": "ethereum", "BSC": "bsc", "TRON": "tron", "SOL": "solana"}
WORMHOLE_CHAINS = {1: "solana", 2: "ethereum", 4: "bsc", 5: "polygon"}
DLN_CHAINS = {1: "ethereum", 56: "bsc", 137: "polygon", 7565164: "solana"}
DLN = "https://stats-api.dln.trade/api"
WORMHOLESCAN = "https://api.wormholescan.io/api/v1/operations"
STABLE = {"USDT", "USDC", "USDC.E", "DAI", "BUSD", "USDT0", "FDUSD"}
# which trackers can see a deposit made on each source chain, in priority order
PROVIDERS = {
    "tron": ("lifi",),
    "bitcoin": ("thorchain", "lifi"),
    "ethereum": ("lifi", "thorchain", "debridge", "wormhole"),
    "bsc": ("lifi", "thorchain", "debridge", "wormhole"),
    "polygon": ("lifi", "debridge", "wormhole"),
    "solana": ("lifi", "debridge", "wormhole"),
}
SWAP_TOOLS = {"thorchain", "chainflip", "mayan", "symbiosis"}


def _ts(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _norm(chain: str, addr: str | None) -> str | None:
    if not addr:
        return None
    return addr.lower() if chain in EVM_CHAINS else addr


def _hit(**kw) -> dict:
    kw.setdefault("confirmed", True)
    kw.setdefault("kind", "swap" if (kw.get("tool") or "").lower() in SWAP_TOOLS else "bridge")
    return kw


async def _usd(symbol: str, amount: float, ts: datetime) -> float:
    s = (symbol or "").upper()
    if s in STABLE:
        return amount
    try:
        return amount * await usd_price(s, ts)
    except Exception:  # noqa: BLE001 - unknown asset price: value stays unknown
        return 0.0


# ---------------- providers ----------------

async def lifi(chain: str, t: Transfer) -> dict | None:
    data = await cached_get("lifi", LIFI_STATUS, {"txHash": t.tx_hash}, ttl_seconds=None, ok_status=(200, 400, 404))
    if not isinstance(data, dict) or data.get("status") != "DONE":
        return None
    snd, rcv = data.get("sending") or {}, data.get("receiving") or {}
    cid = rcv.get("chainId")
    dest_chain = LIFI_CHAINS.get(cid) or f"chain-{cid}"
    dest_addr = _norm(dest_chain, data.get("toAddress") or rcv.get("toAddress") or (data.get("metadata") or {}).get("receiver"))
    if not dest_addr or not rcv.get("txHash") or cid == snd.get("chainId"):
        return None
    ts_in, ts_out = _ts(snd.get("timestamp")) or t.timestamp, _ts(rcv.get("timestamp")) or t.timestamp
    usd_in = float(snd.get("amountUSD") or t.amount_usd or 0)
    tool = data.get("tool") or "lifi"
    return _hit(provider="LI.FI", tool=tool, entity=f"LI.FI ({tool})", dest_chain=dest_chain, dest_address=dest_addr,
                dest_tx=rcv["txHash"], src_tx=t.tx_hash, usd_in=usd_in, usd_out=float(rcv.get("amountUSD") or usd_in),
                ts_in=ts_in, ts_out=ts_out, asset=(rcv.get("token") or {}).get("symbol"))


def midgard_url() -> str:
    return settings().thorchain_midgard_url.rstrip("/")


async def thorchain(chain: str, t: Transfer) -> dict | None:
    txid = t.tx_hash[2:] if t.tx_hash.startswith("0x") else t.tx_hash
    data = await cached_get("midgard", f"{midgard_url()}/actions", {"txid": txid.upper()}, ttl_seconds=None,
                            ok_status=(200, 400, 404))
    for a in (data.get("actions") or []) if isinstance(data, dict) else []:
        if a.get("type") != "swap" or a.get("status") != "success":
            continue
        ins = [i for i in a.get("in", []) if (i.get("txID") or "").upper() == txid.upper()]
        if not ins:
            continue
        swap = (a.get("metadata") or {}).get("swap") or {}
        outs = [o for o in a.get("out", []) if o.get("coins") and o.get("txID") and
                o["coins"][0]["asset"].split(".")[0] in MIDGARD_CHAINS and o["coins"][0]["asset"].split(".")[0] != "THOR"]
        if not outs:
            continue
        o = max(outs, key=lambda x: int(x["coins"][0]["amount"]))
        asset_out = o["coins"][0]["asset"]
        dest_chain = MIDGARD_CHAINS[asset_out.split(".")[0]]
        if dest_chain == chain and asset_out.split(".")[0] == ins[0]["coins"][0]["asset"].split(".")[0]:
            continue  # same-chain swap: not a cross-chain hop
        ts_in = datetime.fromtimestamp(int(a["date"]) / 1e9, tz=timezone.utc)
        ts_out = ts_in + timedelta(seconds=6 * max(0, int(o.get("height") or a["height"]) - int(a["height"])))
        amt_in = int(ins[0]["coins"][0]["amount"]) / 1e8
        amt_out = int(o["coins"][0]["amount"]) / 1e8
        usd_in = amt_in * float(swap.get("inPriceUSD") or 0) or t.amount_usd
        usd_out = amt_out * float(swap.get("outPriceUSD") or 0) or usd_in
        dtx = o["txID"].lower()
        if dest_chain in EVM_CHAINS:
            dtx = "0x" + dtx
        return _hit(provider="THORChain Midgard", tool="thorchain", entity="THORChain", dest_chain=dest_chain,
                    dest_address=_norm(dest_chain, o.get("address")), dest_tx=dtx, src_tx=t.tx_hash, usd_in=usd_in,
                    usd_out=usd_out, ts_in=ts_in, ts_out=ts_out, asset=asset_out.split(".")[1].split("-")[0],
                    memo=swap.get("memo"))
    return None


async def debridge(chain: str, t: Transfer) -> dict | None:
    ids = await cached_get("debridge", f"{DLN}/Transaction/{t.tx_hash}/orderIds", None, ttl_seconds=None,
                           ok_status=(200, 400, 404))
    for oid in ((ids or {}).get("orderIds") or [])[:2] if isinstance(ids, dict) else []:
        o = await cached_get("debridge", f"{DLN}/Orders/{oid.get('stringValue')}", None, ttl_seconds=None)
        if not isinstance(o, dict) or o.get("state") not in ("Fulfilled", "SentUnlock", "ClaimedUnlock"):
            continue
        give, take = o.get("giveOfferWithMetadata") or {}, o.get("takeOfferWithMetadata") or {}
        dcid = int((take.get("chainId") or {}).get("bigIntegerValue") or 0)
        dest_chain = DLN_CHAINS.get(dcid) or f"chain-{dcid}"
        f = o.get("fulfilledDstEventMetadata") or {}
        c = o.get("createdSrcEventMetadata") or {}
        ts_in, ts_out = _ts(c.get("blockTimeStamp")) or t.timestamp, _ts(f.get("blockTimeStamp")) or t.timestamp
        ga = int((give.get("amount") or {}).get("stringValue") or 0) / 10 ** int(give.get("decimals") or 0)
        ta = int((take.get("amount") or {}).get("stringValue") or 0) / 10 ** int(take.get("decimals") or 0)
        usd_in = await _usd(give.get("symbol"), ga, ts_in) or t.amount_usd
        usd_out = await _usd(take.get("symbol"), ta, ts_out) or usd_in
        dtx = ((f.get("transactionHash") or {}).get("stringValue"))
        dest = (o.get("receiverDst") or {}).get("stringValue")
        if not dtx or not dest:
            continue
        return _hit(provider="deBridge DLN", tool="debridge", entity="deBridge", dest_chain=dest_chain,
                    dest_address=_norm(dest_chain, dest), dest_tx=dtx, src_tx=t.tx_hash, usd_in=usd_in, usd_out=usd_out,
                    ts_in=ts_in, ts_out=ts_out, asset=take.get("symbol"))
    return None


async def wormhole(chain: str, t: Transfer) -> dict | None:
    data = await cached_get("wormholescan", WORMHOLESCAN, {"txHash": t.tx_hash}, ttl_seconds=None, ok_status=(200, 400, 404))
    for op in ((data or {}).get("operations") or []) if isinstance(data, dict) else []:
        tgt = op.get("targetChain") or {}
        sp = (op.get("content") or {}).get("standarizedProperties") or {}
        dest_chain = WORMHOLE_CHAINS.get(int(sp.get("toChain") or tgt.get("chainId") or 0))
        dtx = (tgt.get("transaction") or {}).get("txHash")
        dest = sp.get("toAddress") or tgt.get("to")
        if not dest_chain or not dtx or not dest:
            continue
        usd = float((op.get("data") or {}).get("usdAmount") or 0) or t.amount_usd
        return _hit(provider="Wormholescan", tool="wormhole", entity="Wormhole", dest_chain=dest_chain,
                    dest_address=_norm(dest_chain, dest), dest_tx=dtx, src_tx=t.tx_hash, usd_in=usd, usd_out=usd,
                    ts_in=_iso((op.get("sourceChain") or {}).get("timestamp")) or t.timestamp,
                    ts_out=_iso(tgt.get("timestamp")) or t.timestamp, asset=(op.get("data") or {}).get("symbol"))
    return None


_FUNCS = {"lifi": lifi, "thorchain": thorchain, "debridge": debridge, "wormhole": wormhole}


def enabled() -> list[str]:
    s = settings()
    if not s.bridge_tracker:
        return []
    return [p.strip() for p in s.crosschain_providers.split(",") if p.strip() in _FUNCS]


async def resolve(chain: str, txs: list[Transfer], max_tx: int = 3) -> list[dict]:
    """Ask every tracker that can see `chain` about the largest deposits; one hit per source transaction."""
    provs = [p for p in PROVIDERS.get(chain, ()) if p in enabled()]
    hits: list[dict] = []
    seen: set[str] = set()
    for t in sorted(txs, key=lambda t: -t.amount_usd):
        if t.tx_hash in seen:
            continue
        seen.add(t.tx_hash)
        if len(seen) > max_tx:
            break
        results = await asyncio.gather(*(_FUNCS[p](chain, t) for p in provs), return_exceptions=True)
        for r in results:  # provider priority order
            if isinstance(r, dict):
                hits.append(r)
                break
    return hits


async def same_address_match(chain: str, address: str, t: Transfer, adapter_for, cfg: dict) -> dict | None:
    """Fallback when no tracker knows the deposit: did ~the same value (minus a bridge fee) reach the SAME EVM
    address on another EVM chain soon after? Bridges default to sending to the depositor's own address."""
    if chain not in EVM_CHAINS:
        return None
    m = cfg["continuity"]
    window = timedelta(hours=m.get("match_window_hours", 6))
    for other in EVM_CHAINS:
        if other == chain:
            continue
        try:
            ins = await adapter_for(other).get_transfers(address, "in", t.timestamp, t.timestamp + window)
        except AdapterUnavailable:
            continue
        for x in sorted(ins, key=lambda x: x.timestamp):
            if x.timestamp < t.timestamp or not t.amount_usd:
                continue
            loss = (t.amount_usd - x.amount_usd) / t.amount_usd
            if -0.001 <= loss <= m.get("max_fee_share", 0.03):
                return _hit(provider="heuristic", tool="same-address match", entity="Bridge (unconfirmed)",
                            dest_chain=other, dest_address=address, dest_tx=x.tx_hash, src_tx=t.tx_hash,
                            usd_in=t.amount_usd, usd_out=x.amount_usd, ts_in=t.timestamp, ts_out=x.timestamp,
                            asset=x.asset, confirmed=False)
    return None
