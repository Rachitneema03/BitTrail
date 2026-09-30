"""Solana adapter via standard JSON-RPC (public endpoint by default; SOLANA_RPC_URL for Helius / QuickNode).

Transfers followed:
- native SOL: system-program `transfer` instructions (top-level and inner)
- USDT / USDC: per-owner token-balance deltas of a transaction (one sender -> receivers, or senders -> one receiver);
  multi-party swaps are skipped rather than guessed.
Each address query reads up to MAX_SIGS recent signatures in the time window (one RPC call per transaction).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from ..config import settings
from .base import AdapterUnavailable, AddressInfo, Transfer
from .http import cached_get
from .prices import usd_price

TOKENS = {
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": ("USDT", 6),
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": ("USDC", 6),
}
PAGE = 40
MAX_SIGS = 40


class SolanaAdapter:
    chain = "solana"

    async def _rpc(self, method: str, params: list, ttl: int | None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = await cached_get("solana", settings().solana_rpc_url, None, None, ttl, retries=6, json_body=body)
        if isinstance(data, dict) and data.get("error"):
            raise AdapterUnavailable(f"solana rpc {method}: {data['error'].get('message', data['error'])}")
        return data.get("result") if isinstance(data, dict) else None

    async def _signatures(self, address: str, since: datetime | None, until: datetime | None) -> list[dict]:
        live = until is None or until > datetime.now(timezone.utc)
        sigs, before = [], None
        while len(sigs) < MAX_SIGS:
            opts = {"limit": PAGE, **({"before": before} if before else {})}
            page = await self._rpc("getSignaturesForAddress", [address, opts], 300 if live and before is None else None) or []
            if not page:
                break
            for s in page:
                bt = s.get("blockTime")
                if bt is None or s.get("err") is not None:
                    continue
                ts = datetime.fromtimestamp(bt, tz=timezone.utc)
                if until and ts > until:
                    continue
                if since and ts < since:
                    return sigs
                sigs.append(s)
            if len(page) < PAGE:
                break
            before = page[-1]["signature"]
        return sigs[:MAX_SIGS]

    async def _token_accounts(self, owner: str) -> list[str]:
        """USDT/USDC token accounts of a wallet: SPL transfers are recorded against these, not the owner."""
        accs: list[str] = []
        for mint in TOKENS:
            try:
                r = await self._rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}], 3600) or {}
            except AdapterUnavailable:
                continue
            accs += [v["pubkey"] for v in (r.get("value") or [])[:2]]
        return accs

    async def _all_signatures(self, owner: str, since, until) -> list[dict]:
        seen, out = set(), []
        for addr in [owner, *await self._token_accounts(owner)]:
            for s in await self._signatures(addr, since, until):
                if s["signature"] not in seen:
                    seen.add(s["signature"])
                    out.append(s)
        return sorted(out, key=lambda s: s["blockTime"])[:MAX_SIGS * 2]

    async def _parse(self, sig: str) -> list[Transfer]:
        tx = await self._rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}], None)
        if not tx or not tx.get("blockTime") or (tx.get("meta") or {}).get("err"):
            return []
        ts = datetime.fromtimestamp(tx["blockTime"], tz=timezone.utc)
        slot = tx.get("slot")
        meta = tx.get("meta") or {}
        out: list[Transfer] = []
        # native SOL
        ixs = list(tx.get("transaction", {}).get("message", {}).get("instructions", []))
        for inner in meta.get("innerInstructions") or []:
            ixs.extend(inner.get("instructions", []))
        price = None
        for ix in ixs:
            p = ix.get("parsed")
            if ix.get("program") != "system" or not isinstance(p, dict) or p.get("type") not in ("transfer", "transferWithSeed"):
                continue
            info = p.get("info", {})
            lamports = int(info.get("lamports", 0))
            if lamports <= 0 or not info.get("source") or not info.get("destination"):
                continue
            price = price if price is not None else await usd_price("SOL", ts)
            amt = lamports / 1e9
            out.append(Transfer("solana", sig, len(out), slot, ts, info["source"], info["destination"], "SOL", None,
                                str(lamports), 9, amt, amt * price))
        # SPL stablecoins by owner balance deltas
        deltas: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for sign, key in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
            for b in meta.get(key) or []:
                mint, owner = b.get("mint"), b.get("owner")
                if mint in TOKENS and owner:
                    deltas[mint][owner] += sign * int((b.get("uiTokenAmount") or {}).get("amount") or 0)
        for mint, per_owner in deltas.items():
            sym, dec = TOKENS[mint]
            senders = {o: -d for o, d in per_owner.items() if d < 0}
            receivers = {o: d for o, d in per_owner.items() if d > 0}
            pairs = []
            if len(senders) == 1:
                s = next(iter(senders))
                pairs = [(s, r, d) for r, d in receivers.items()]
            elif len(receivers) == 1:
                r = next(iter(receivers))
                pairs = [(s, r, d) for s, d in senders.items()]
            for frm, to, raw in pairs:
                amt = raw / 10**dec
                out.append(Transfer("solana", sig, len(out), slot, ts, frm, to, sym, mint, str(raw), dec, amt, amt))
        return out

    async def get_transfers(self, address, direction, since, until, limit=200):
        out: list[Transfer] = []
        for s in await self._all_signatures(address, since, until):
            try:
                parsed = await self._parse(s["signature"])
            except AdapterUnavailable:
                continue  # one throttled / missing transaction must not sink the whole query
            for t in parsed:
                if (direction == "out" and t.from_address == address) or (direction == "in" and t.to_address == address):
                    out.append(t)
        out.sort(key=lambda x: x.timestamp, reverse=(direction == "in"))
        return out[:limit]

    async def get_info(self, address):
        now = datetime.now(timezone.utc)
        bal = await self._rpc("getBalance", [address], 120) or {}
        balances: dict[str, float] = {}
        sol = (bal.get("value") or 0) / 1e9
        if sol:
            balances["SOL"] = sol
        for mint, (sym, _) in TOKENS.items():
            r = await self._rpc("getTokenAccountsByOwner", [address, {"mint": mint}, {"encoding": "jsonParsed"}], 120) or {}
            amt = sum(float(a["account"]["data"]["parsed"]["info"]["tokenAmount"].get("uiAmount") or 0)
                      for a in r.get("value", []))
            if amt:
                balances[sym] = amt
        usd = sum([v * await usd_price(k, now) for k, v in balances.items()])
        return AddressInfo(balance_usd=usd, balances=balances)

    async def chain_height(self):
        return await self._rpc("getSlot", [], 30)
