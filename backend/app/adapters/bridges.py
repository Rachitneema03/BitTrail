"""Cross-chain destination lookup via the LI.FI status API (free, no key).

Given the transfers that entered a labelled bridge, ask LI.FI whether that source transaction was bridged, and
where it landed. Returns None when LI.FI does not know the transaction (not a LI.FI-tracked bridge, or pending).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from .base import AdapterUnavailable, Transfer
from .http import cached_get

STATUS = "https://li.quest/v1/status"
CHAIN_IDS = {1: "ethereum", 137: "polygon", 56: "bsc", 1151111081099710: "solana"}


def _ts(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


async def lifi_resolver(chain: str, txs: list[Transfer]) -> dict | None:
    if not settings().bridge_tracker:
        return None
    for t in sorted(txs, key=lambda t: -t.amount_usd)[:2]:
        try:
            data = await cached_get("lifi", STATUS, {"txHash": t.tx_hash}, ttl_seconds=None)
        except AdapterUnavailable:
            continue
        if not isinstance(data, dict) or data.get("status") != "DONE":
            continue
        snd, rcv = data.get("sending") or {}, data.get("receiving") or {}
        dest_chain = CHAIN_IDS.get(rcv.get("chainId"))
        dest_addr = data.get("toAddress") or rcv.get("toAddress") or (data.get("metadata") or {}).get("receiver")
        if not dest_chain or not dest_addr or not rcv.get("txHash"):
            continue
        ts_in, ts_out = _ts(snd.get("timestamp")) or t.timestamp, _ts(rcv.get("timestamp")) or t.timestamp
        usd_in = float(snd.get("amountUSD") or t.amount_usd or 0)
        usd_out = float(rcv.get("amountUSD") or usd_in)
        if dest_chain in ("ethereum", "polygon", "bsc"):
            dest_addr = dest_addr.lower()
        return {"dest_chain": dest_chain, "dest_address": dest_addr, "dest_tx": rcv["txHash"], "usd_in": usd_in,
                "usd_out": usd_out, "ts_in": ts_in, "ts_out": ts_out, "tool": data.get("tool"),
                "asset": (rcv.get("token") or {}).get("symbol")}
    return None
