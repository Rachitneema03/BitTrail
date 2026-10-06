"""Ethereum / Polygon / BNB Chain adapter (Etherscan-compatible "account" API).

Provider per chain, first that is configured:
- Etherscan API V2 (ETHERSCAN_API_KEY, one key, chainid switch)
- BNB Chain only: BSC_API_BASE (+ BSC_API_KEY), any Etherscan-compatible BNB Chain API
- Ethereum / Polygon only: Blockscout REST API v2 (no key; ~180 requests per minute). Blockscout's
  Etherscan-compatible /api endpoint is NOT used: keyless it allows 10 requests, then locks out for ~30 minutes.
BNB Chain has no keyless history source (Etherscan's free tier excludes it; public RPCs refuse archive log queries),
so it needs a paid Etherscan key or BSC_API_BASE.
Follows native ETH/POL/BNB and whitelisted stablecoins.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from .base import AdapterUnavailable, AddressInfo, Transfer
from .http import cached_get
from .prices import usd_price

BASE = "https://api.etherscan.io/v2/api"
BLOCKSCOUT = {"ethereum": "https://eth.blockscout.com/api/v2", "polygon": "https://polygon.blockscout.com/api/v2"}
BLOCKSCOUT_PAGES = 4  # 50 items per page, newest first
CHAINS = {
    "ethereum": {"chainid": 1, "native": "ETH", "tokens": {
        "0xdac17f958d2ee523a2206206994597c13d831ec7": ("USDT", 6),
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": ("USDC", 6)}},
    "polygon": {"chainid": 137, "native": "POL", "tokens": {
        "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": ("USDT", 6),
        "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": ("USDC", 6),
        "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": ("USDC.E", 6)}},
    "bsc": {"chainid": 56, "native": "BNB", "tokens": {
        "0x55d398326f99059ff775485246999027b3197955": ("USDT", 18),
        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18)}},
}


def provider_for(chain: str) -> tuple[str, str, str] | None:
    """(base_url, api_key, cache_provider_name) for a chain, or None when the chain has no usable source."""
    s = settings()
    if chain == "bsc" and s.bsc_api_base:
        return s.bsc_api_base, s.bsc_api_key or s.etherscan_api_key, "bscapi"
    if s.etherscan_api_key and (chain != "bsc" or s.etherscan_bsc):
        return BASE, s.etherscan_api_key, "etherscan"
    if chain in BLOCKSCOUT and s.blockscout_fallback:
        return BLOCKSCOUT[chain], "", "blockscout"
    return None


def provider_name(chain: str) -> str:
    p = provider_for(chain)
    if p is None:
        return "not configured (needs a paid Etherscan key or BSC_API_BASE)" if chain == "bsc" else "not configured"
    return {"etherscan": f"Etherscan API V2 (chainid {CHAINS[chain]['chainid']})", "bscapi": "BSC_API_BASE",
            "blockscout": f"Blockscout REST API v2 ({BLOCKSCOUT.get(chain, '')})"}[p[2]]


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class EvmAdapter:
    def __init__(self, chain: str):
        self.chain = chain
        self.cfg = CHAINS[chain]

    def _keyless(self) -> bool:
        p = provider_for(self.chain)
        return p is not None and p[2] == "blockscout"

    # ---------------- Blockscout REST API v2 (keyless Ethereum / Polygon) ----------------
    async def _bs(self, path: str, params: dict | None, ttl: int | None):
        try:
            return await cached_get("blockscout", f"{BLOCKSCOUT[self.chain]}{path}", params, ttl_seconds=ttl)
        except AdapterUnavailable as e:
            raise AdapterUnavailable(f"{e} (keyless Blockscout; set ETHERSCAN_API_KEY for higher limits)") from None

    async def _bs_pages(self, path: str, params: dict, since: datetime | None, ttl: int | None) -> list[dict]:
        """Newest-first pages until items are older than `since` (or the page budget runs out)."""
        items: list[dict] = []
        q = dict(params)
        for _ in range(BLOCKSCOUT_PAGES):
            data = await self._bs(path, q, ttl)
            page = (data.get("items") or []) if isinstance(data, dict) else []
            items += page
            nxt = data.get("next_page_params") if isinstance(data, dict) else None
            if not nxt or not page or (since and _iso(page[-1]["timestamp"]) < since):
                break
            q = {**params, **nxt}
        return items

    async def _bs_transfers(self, address: str, direction: str, since, until) -> list[Transfer]:
        live = until is None or until > datetime.now(timezone.utc)
        ttl = 300 if live else None
        flt = "from" if direction == "out" else "to"
        out: list[Transfer] = []
        for t in await self._bs_pages(f"/addresses/{address}/token-transfers", {"type": "ERC-20", "filter": flt}, since, ttl):
            contract = ((t.get("token") or {}).get("address_hash") or (t.get("token") or {}).get("address") or "").lower()
            if contract not in self.cfg["tokens"]:
                continue  # look-alike / scam tokens share the symbol, not the contract (address poisoning)
            frm, to = ((t.get("from") or {}).get("hash") or "").lower(), ((t.get("to") or {}).get("hash") or "").lower()
            if (direction == "out" and frm != address) or (direction == "in" and to != address):
                continue
            sym, dec = self.cfg["tokens"][contract]
            raw = int((t.get("total") or {}).get("value") or 0)
            ts = _iso(t["timestamp"])
            if raw <= 0 or (since and ts < since) or (until and ts > until):
                continue
            amt = raw / 10**dec
            out.append(Transfer(self.chain, t["transaction_hash"], int(t.get("log_index") or 0), t.get("block_number"), ts,
                                frm, to, sym, contract, str(raw), dec, amt, amt))
        for t in await self._bs_pages(f"/addresses/{address}/transactions", {"filter": flt}, since, ttl):
            if t.get("result") not in (None, "success") or t.get("status") not in (None, "ok"):
                continue
            frm, to = ((t.get("from") or {}).get("hash") or "").lower(), ((t.get("to") or {}).get("hash") or "").lower()
            raw = int(t.get("value") or 0)
            ts = _iso(t["timestamp"])
            if not to or raw <= 0 or (since and ts < since) or (until and ts > until):
                continue
            if (direction == "out" and frm != address) or (direction == "in" and to != address):
                continue
            amt = raw / 1e18
            out.append(Transfer(self.chain, t["hash"], -1, t.get("block_number"), ts, frm, to, self.cfg["native"], None,
                                str(raw), 18, amt, amt * await usd_price(self.cfg["native"], ts)))
        return out

    async def _call(self, params: dict, ttl: int | None):
        p = provider_for(self.chain)
        if p is None and not settings().demo_mode:
            raise AdapterUnavailable(
                "BNB Chain needs a paid Etherscan key (ETHERSCAN_BSC=1) or BSC_API_BASE" if self.chain == "bsc"
                else f"no data source configured for {self.chain}")
        base, key, provider = p or (BASE, "", "etherscan")
        q = {**params} if provider == "blockscout" else {"chainid": self.cfg["chainid"], **params, "apikey": key}
        data = await cached_get(provider, base, q, ttl_seconds=ttl)
        if isinstance(data, dict) and data.get("status") == "0":
            msg = str(data.get("message")) + " " + str(data.get("result"))
            if data.get("result") in ([], None) or "no " in msg.lower() and "found" in msg.lower() or "No transactions" in msg:
                return []
            if self.chain == "bsc" and "not supported" in msg.lower():
                raise AdapterUnavailable("BNB Chain needs a paid Etherscan key or BSC_API_BASE (Etherscan-compatible API)")
            raise AdapterUnavailable(f"{provider}: {msg[:160]}")
        return data.get("result", []) if isinstance(data, dict) else []

    async def _block_at(self, ts: datetime, closest: str) -> int:
        r = await self._call({"module": "block", "action": "getblocknobytime", "timestamp": int(ts.timestamp()),
                              "closest": closest}, ttl=None)
        if isinstance(r, dict):  # Blockscout wraps it: {"blockNumber": "..."}
            r = r.get("blockNumber")
        return int(r) if str(r).isdigit() else (0 if closest == "after" else 99999999)

    async def get_transfers(self, address, direction, since, until, limit=200):
        address = address.lower()
        if self._keyless():
            out = await self._bs_transfers(address, direction, since, until)
            out.sort(key=lambda x: x.timestamp, reverse=(direction == "in"))
            return out[:limit]
        start = await self._block_at(since, "after") if since else 0
        live = until is None or until > datetime.now(timezone.utc)
        end = 99999999 if live else await self._block_at(until, "before")
        sort = "asc" if direction == "out" else "desc"
        base = {"module": "account", "address": address, "startblock": start, "endblock": end,
                "page": 1, "offset": 200, "sort": sort}
        ttl = 300 if live else None
        out: list[Transfer] = []
        for t in await self._call({**base, "action": "tokentx"}, ttl):
            contract = (t.get("contractAddress") or "").lower()
            if contract not in self.cfg["tokens"]:
                continue
            frm, to = (t.get("from") or "").lower(), (t.get("to") or "").lower()
            if (direction == "out" and frm != address) or (direction == "in" and to != address):
                continue
            sym, dec = self.cfg["tokens"][contract]
            raw = int(t.get("value") or 0)
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
            raw = int(t.get("value") or 0)
            if raw <= 0:
                continue
            amt = raw / 1e18
            ts = datetime.fromtimestamp(int(t["timeStamp"]), tz=timezone.utc)
            usd = amt * await usd_price(self.cfg["native"], ts)
            out.append(Transfer(self.chain, t["hash"], -1, int(t["blockNumber"]), ts, frm, to, self.cfg["native"],
                                None, str(raw), 18, amt, usd))
        out.sort(key=lambda x: x.timestamp, reverse=(direction == "in"))
        return out[:limit]

    async def has_activity(self, address: str, since: datetime | None) -> bool:
        """Cheap check used to find which EVM chains an address is active on (same address, many chains)."""
        if provider_for(self.chain) is None and not settings().demo_mode:
            return False
        try:
            outs = await self.get_transfers(address, "out", since, None, limit=5)
        except AdapterUnavailable:
            return False
        return any(t.amount_usd >= 1 for t in outs)

    async def get_info(self, address):
        address = address.lower()
        now = datetime.now(timezone.utc)
        if self._keyless():
            a = await self._bs(f"/addresses/{address}", None, 120)
            balances = {self.cfg["native"]: int(a.get("coin_balance") or 0) / 1e18} if isinstance(a, dict) else {}
            tb = await self._bs(f"/addresses/{address}/token-balances", None, 120)
            for row in tb if isinstance(tb, list) else []:
                contract = ((row.get("token") or {}).get("address_hash") or "").lower()
                if contract in self.cfg["tokens"] and int(row.get("value") or 0) > 0:
                    sym, dec = self.cfg["tokens"][contract]
                    balances[sym] = int(row["value"]) / 10**dec
            balances = {k: v for k, v in balances.items() if v}
            usd = sum([v * await usd_price(k, now) for k, v in balances.items()])
            return AddressInfo(balance_usd=usd, balances=balances)
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
        if self._keyless():
            blocks = await self._bs("/main-page/blocks", None, 30)
            return int(blocks[0]["height"]) if isinstance(blocks, list) and blocks else None
        r = await self._call({"module": "proxy", "action": "eth_blockNumber"}, ttl=30)
        return int(r, 16) if isinstance(r, str) and r.startswith("0x") else (int(r) if str(r).isdigit() else None)
