"""Ethereum / Polygon adapter via Etherscan API V2 (one key, chainid switch).

Requires ETHERSCAN_API_KEY. Follows native ETH/POL and whitelisted stablecoins.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from .base import AdapterUnavailable, AddressInfo, Transfer
from .http import cached_get
from .prices import usd_price

BASE = "https://api.etherscan.io/v2/api"
CHAINS = {
    "ethereum": {"chainid": 1, "native": "ETH", "tokens": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6)}},
    "polygon": {"chainid": 137, "native": "POL", "tokens": {
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": ("USDT", 6),
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": ("USDC", 6),
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": ("USDC.E", 6)}},
}


class EvmAdapter:
    def __init__(self, chain: str):
        self.chain = chain
        self.cfg = CHAINS[chain]

    async def _call(self, params: dict, ttl: int | None):
        key = settings().etherscan_api_key
        if not key and not settings().demo_mode:
            raise AdapterUnavailable("ETHERSCAN_API_KEY not set: Ethereum/Polygon tracing disabled")
        p = {"chainid": self.cfg["chainid"], **params, "apikey": key}
        data = await cached_get("etherscan", BASE, p, ttl_seconds=ttl)
        if isinstance(data, dict) and data.get("status") == "0" and "No transactions" not in str(data.get("message")):
            if data.get("result") in ([], None):
                return []
            raise AdapterUnavailable(f"etherscan: {data.get('message')} {str(data.get('result'))[:120]}")
        return data.get("result", []) if isinstance(data, dict) else []

    async def _block_at(self, ts: datetime, closest: str) -> int:
        r = await self._call({"module": "block", "action": "getblocknobytime", "timestamp": int(ts.timestamp()),
                              "closest": closest}, ttl=None)
        return int(r) if str(r).isdigit() else (0 if closest == "after" else 99999999)

    async def get_transfers(self, address, direction, since, until, limit=200):
        address = address.lower()
        start = await self._block_at(since, "after") if since else 0
        live = until is None or until > datetime.now(timezone.utc)
        end = 99999999 if live else await self._block_at(until, "before")
        sort = "asc" if direction == "out" else "desc"
        base = {"module": "account", "address": address, "startblock": start, "endblock": end,
                "page": 1, "offset": 200, "sort": sort}
        ttl = 300 if live else None
        out: list[Transfer] = []
        for t in await self._call({**base, "action": "tokentx"}, ttl):
            contract = t.get("contractAddress", "").lower()
            if contract not in self.cfg["tokens"]:
                continue
            frm, to = t["from"].lower(), t["to"].lower()
            if (direction == "out" and frm != address) or (direction == "in" and to != address):
                continue
            sym, dec = self.cfg["tokens"][contract]
            raw = int(t["value"])
            if raw <= 0:
                continue
            amt = raw / 10**dec
            ts = datetime.fromtimestamp(int(t["timeStamp"]), tz=timezone.utc)
            out.append(Transfer(self.chain, t["hash"], int(t.get("logIndex") or 0), int(t["blockNumber"]), ts,
                                frm, to, sym, contract, str(raw), dec, amt, amt))
        for t in await self._call({**base, "action": "txlist"}, ttl):
            if t.get("isError") == "1" or not t.get("to"):
                continue
            frm, to = t["from"].lower(), t["to"].lower()
            if (direction == "out" and frm != address) or (direction == "in" and to != address):
                continue
            raw = int(t["value"])
            if raw <= 0:
                continue
            amt = raw / 1e18
            ts = datetime.fromtimestamp(int(t["timeStamp"]), tz=timezone.utc)
            usd = amt * await usd_price(self.cfg["native"], ts)
            out.append(Transfer(self.chain, t["hash"], -1, int(t["blockNumber"]), ts, frm, to, self.cfg["native"],
                                None, str(raw), 18, amt, usd))
        out.sort(key=lambda x: x.timestamp, reverse=(direction == "in"))
        return out[:limit]

    async def get_info(self, address):
        address = address.lower()
        now = datetime.now(timezone.utc)
        bal = await self._call({"module": "account", "action": "balance", "address": address, "tag": "latest"}, 120)
        balances = {self.cfg["native"]: int(bal) / 1e18} if str(bal).isdigit() else {}
        for contract, (sym, dec) in self.cfg["tokens"].items():
            r = await self._call({"module": "account", "action": "tokenbalance", "contractaddress": contract,
                                  "address": address, "tag": "latest"}, 120)
            if str(r).isdigit() and int(r) > 0:
                balances[sym] = int(r) / 10**dec
        usd = sum([v * await usd_price(k, now) for k, v in balances.items()])
        return AddressInfo(balance_usd=usd, balances=balances)

    async def chain_height(self):
        r = await self._call({"module": "proxy", "action": "eth_blockNumber"}, ttl=30)
        return int(r, 16) if isinstance(r, str) and r.startswith("0x") else None
