"""Bitcoin adapter (mempool.space).

MVP model: an outgoing transfer is each output of a spending tx that does not return to
the same address, scaled by this address's share of the tx inputs. No change detection yet.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .base import AddressInfo, Transfer
from .http import cached_get
from .prices import usd_price

BASE = "https://mempool.space/api"
MAX_PAGES = 8  # 25 txs per page


class BtcAdapter:
    chain = "bitcoin"

    async def _txs(self, address: str) -> list[dict]:
        txs: list[dict] = []
        last = None
        for _ in range(MAX_PAGES):
            url = f"{BASE}/address/{address}/txs/chain" + (f"/{last}" if last else "")
            page = await cached_get("mempool", url, None, ttl_seconds=300)
            if not page:
                break
            txs.extend(page)
            if len(page) < 25:
                break
            last = page[-1]["txid"]
        return txs

    async def get_transfers(self, address, direction, since, until, limit=200):
        out: list[Transfer] = []
        for tx in await self._txs(address):
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
                for i, o in enumerate(tx.get("vout", [])):
                    to = o.get("scriptpubkey_address")
                    if not to or to == address:
                        continue
                    sats = int(o.get("value", 0) * share)
                    if sats <= 0:
                        continue
                    amt = sats / 1e8
                    out.append(Transfer("bitcoin", tx["txid"], i, height, ts, address, to, "BTC", None,
                                        str(sats), 8, amt, amt * price))
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
        d = await cached_get("mempool", f"{BASE}/address/{address}", None, ttl_seconds=120)
        cs = d.get("chain_stats", {})
        sats = cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)
        btc = sats / 1e8
        usd = btc * await usd_price("BTC", datetime.now(timezone.utc))
        return AddressInfo(balance_usd=usd, balances={"BTC": btc} if btc else {}, tx_count=cs.get("tx_count"))

    async def chain_height(self):
        r = await cached_get("mempool", f"{BASE}/blocks/tip/height", None, ttl_seconds=30)
        return int(r) if isinstance(r, (int, float)) else None
