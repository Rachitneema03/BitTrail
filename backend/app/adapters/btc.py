"""Bitcoin adapter (mempool.space).

MVP model: an outgoing transfer is each output of a spending tx that does not return to
the same address, scaled by this address's share of the tx inputs. No change detection yet.
Equal-output CoinJoin transactions are tagged "coinjoin" (thresholds in heuristics.yaml): the engine treats them
as a mixer and stops there.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from ..config import heuristics
from .base import AdapterUnavailable, AddressInfo, Transfer
from .http import cached_get
from .prices import usd_price

# Esplora-compatible APIs, tried in order (same paths, same JSON). A provider that is down or blocks us trips the
# HTTP layer's breaker, so the next one is used immediately.
ESPLORA = [("mempool", "https://mempool.space/api"), ("blockstream", "https://blockstream.info/api")]
MAX_PAGES = 8  # 25 txs per page


async def esplora(path: str, ttl: int | None):
    last: Exception | None = None
    for provider, base in ESPLORA:
        try:
            return await cached_get(provider, f"{base}{path}", None, ttl_seconds=ttl)
        except AdapterUnavailable as e:
            last = e
    raise AdapterUnavailable(f"bitcoin: no Esplora API reachable ({last})")


def is_coinjoin(tx: dict) -> bool:
    c = heuristics().get("coinjoin", {})
    values = [o.get("value") for o in tx.get("vout", []) if o.get("value")]
    if not values or len(tx.get("vin", [])) < c.get("min_inputs", 5):
        return False
    _, n = Counter(values).most_common(1)[0]
    return n >= c.get("min_equal_outputs", 5) and n / len(values) >= c.get("min_equal_share", 0.4)


class BtcAdapter:
    chain = "bitcoin"

    async def _txs(self, address: str, since: datetime | None = None) -> list[dict]:
        """Confirmed txs, newest first; stops paging once a page reaches back past `since`."""
        txs: list[dict] = []
        last = None
        for _ in range(MAX_PAGES):
            path = f"/address/{address}/txs/chain" + (f"/{last}" if last else "")
            # later pages are fixed history (keyed by the last txid seen): cache them for good
            page = await esplora(path, 300 if last is None else None)
            if not page:
                break
            txs.extend(page)
            oldest = (page[-1].get("status") or {}).get("block_time")
            if len(page) < 25 or (since and oldest and oldest < since.timestamp()):
                break
            last = page[-1]["txid"]
        return txs

    async def get_transfers(self, address, direction, since, until, limit=200):
        out: list[Transfer] = []
        for tx in await self._txs(address, since):
            bt = tx.get("status", {}).get("block_time")
            if not bt:
                continue
            ts = datetime.fromtimestamp(bt, tz=timezone.utc)
            if (since and ts < since) or (until and ts > until):
                continue
            price = await usd_price("BTC", ts)
            vin = [v.get("prevout") or {} for v in tx.get("vin", [])]
            total_in = sum(p.get("value", 0) for p in vin) or 1
            height = tx.get("status", {}).get("block_height")
            if direction == "out":
                mine = sum(p.get("value", 0) for p in vin if p.get("scriptpubkey_address") == address)
                if not mine:
                    continue
                share = mine / total_in
                tags = ("coinjoin",) if is_coinjoin(tx) else ()
                for i, o in enumerate(tx.get("vout", [])):
                    to = o.get("scriptpubkey_address")
                    if not to or to == address:
                        continue
                    sats = int(o.get("value", 0) * share)
                    if sats <= 0:
                        continue
                    amt = sats / 1e8
                    out.append(Transfer("bitcoin", tx["txid"], i, height, ts, address, to, "BTC", None,
                                        str(sats), 8, amt, amt * price, tags))
            else:
                recv = sum(o.get("value", 0) for o in tx.get("vout", []) if o.get("scriptpubkey_address") == address)
                if not recv:
                    continue
                senders: dict[str, int] = {}
                for p in vin:
                    a = p.get("scriptpubkey_address")
                    if a and a != address:
                        senders[a] = senders.get(a, 0) + p.get("value", 0)
                for i, (frm, val) in enumerate(senders.items()):
                    sats = int(recv * val / total_in)
                    if sats <= 0:
                        continue
                    amt = sats / 1e8
                    out.append(Transfer("bitcoin", tx["txid"], i, height, ts, frm, address, "BTC", None,
                                        str(sats), 8, amt, amt * price))
        out.sort(key=lambda x: x.timestamp, reverse=(direction == "in"))
        return out[:limit]

    async def get_info(self, address):
        d = await esplora(f"/address/{address}", 120)
        cs = d.get("chain_stats", {})
        sats = cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)
        btc = sats / 1e8
        usd = btc * await usd_price("BTC", datetime.now(timezone.utc))
        return AddressInfo(balance_usd=usd, balances={"BTC": btc} if btc else {}, tx_count=cs.get("tx_count"))

    async def chain_height(self):
        r = await esplora("/blocks/tip/height", 30)
        return int(r) if isinstance(r, (int, float)) else None
