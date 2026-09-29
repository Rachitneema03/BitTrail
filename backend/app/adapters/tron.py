"""Tron adapter (TronGrid). Covers native TRX and whitelisted stablecoin TRC-20 transfers.

Only whitelisted token contracts are followed: scam "USDT" look-alike tokens (address
poisoning) share the symbol but not the contract.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from ..config import settings
from .base import AddressInfo, Transfer
from .http import cached_get
from .prices import usd_price

BASE = "https://api.trongrid.io"
TOKENS = {
    "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": ("USDT", 6),
    "TEkxiTehnzSmSe2XqrBj4w32RUN966rdz8": ("USDC", 6),
}
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def hex_to_base58(h: str) -> str:
    raw = bytes.fromhex(h)
    chk = hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
    n = int.from_bytes(raw + chk, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    pad = len(raw + chk) - len((raw + chk).lstrip(b"\0"))
    return "1" * pad + out


def _ms(dt: datetime | None) -> int | None:
    return int(dt.timestamp() * 1000) if dt else None


def _ttl(until: datetime | None) -> int | None:
    # queries ending in the past are immutable; open-ended ones refresh every 5 min
    if until and until < datetime.now(timezone.utc):
        return None
    return 300


class TronAdapter:
    chain = "tron"

    def _headers(self) -> dict:
        key = settings().trongrid_api_key
        return {"TRON-PRO-API-KEY": key} if key else {}

    async def get_transfers(self, address, direction, since, until, limit=200):
        order = "block_timestamp,asc" if direction == "out" else "block_timestamp,desc"
        flag = "only_from" if direction == "out" else "only_to"
        params = {"limit": min(limit, 200), flag: "true", "only_confirmed": "true", "order_by": order}
        if since:
            params["min_timestamp"] = _ms(since)
        if until:
            params["max_timestamp"] = _ms(until)
        out: list[Transfer] = []

        trc20 = await cached_get("trongrid", f"{BASE}/v1/accounts/{address}/transactions/trc20", params,
                                 self._headers(), _ttl(until))
        for i, t in enumerate(trc20.get("data", [])):
            info = t.get("token_info") or {}
            contract = info.get("address")
            if contract not in TOKENS:
                continue
            sym, dec = TOKENS[contract]
            raw = int(t.get("value") or 0)
            if raw <= 0:
                continue
            amt = raw / 10**dec
            ts = datetime.fromtimestamp(t["block_timestamp"] / 1000, tz=timezone.utc)
            out.append(Transfer("tron", t["transaction_id"], i, None, ts, t["from"], t["to"], sym, contract,
                                str(raw), dec, amt, amt))

        native = await cached_get("trongrid", f"{BASE}/v1/accounts/{address}/transactions", params,
                                  self._headers(), _ttl(until))
        for t in native.get("data", []):
            try:
                c = t["raw_data"]["contract"][0]
                if c["type"] != "TransferContract" or t.get("ret", [{}])[0].get("contractRet") != "SUCCESS":
                    continue
                v = c["parameter"]["value"]
                raw = int(v["amount"])
                frm, to = hex_to_base58(v["owner_address"]), hex_to_base58(v["to_address"])
            except (KeyError, IndexError, ValueError):
                continue
            if raw <= 0:
                continue
            ts = datetime.fromtimestamp(t["block_timestamp"] / 1000, tz=timezone.utc)
            amt = raw / 1e6
            usd = amt * await usd_price("TRX", ts)
            out.append(Transfer("tron", t["txID"], 0, t.get("blockNumber"), ts, frm, to, "TRX", None,
                                str(raw), 6, amt, usd))

        out.sort(key=lambda x: x.timestamp, reverse=(direction == "in"))
        return out[:limit]

    async def get_info(self, address):
        data = await cached_get("trongrid", f"{BASE}/v1/accounts/{address}", None, self._headers(), ttl_seconds=120)
        rows = data.get("data") or []
        if not rows:
            return AddressInfo(balance_usd=0.0, balances={})
        acc = rows[0]
        balances: dict[str, float] = {}
        trx = int(acc.get("balance") or 0) / 1e6
        if trx:
            balances["TRX"] = trx
        for entry in acc.get("trc20") or []:
            for contract, val in entry.items():
                if contract in TOKENS:
                    sym, dec = TOKENS[contract]
                    balances[sym] = balances.get(sym, 0) + int(val) / 10**dec
        now = datetime.now(timezone.utc)
        usd = sum([v * await usd_price(k, now) for k, v in balances.items()])
        return AddressInfo(balance_usd=usd, balances=balances)

    async def chain_height(self):
        data = await cached_get("trongrid", f"{BASE}/wallet/getnowblock", None, self._headers(), ttl_seconds=30)
        return data.get("block_header", {}).get("raw_data", {}).get("number")
