"""Read-through cached HTTP client used by every adapter.

- Every response is stored in `api_cache` keyed by provider + url + sorted params.
- Historical queries (fully in the past) never expire; "live" queries use a short TTL.
- DEMO_MODE serves only from the cache; a miss raises AdapterUnavailable.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone

import httpx

from ..config import settings
from ..db import SessionLocal
from ..models import ApiCache
from .base import AdapterUnavailable

# minimum seconds between calls, per provider (free tiers)
MIN_INTERVAL = {"trongrid": 0.4, "etherscan": 0.25, "bscapi": 0.25, "blockscout": 0.35, "mempool": 0.3, "binance": 0.1,
                "solana": 0.6, "lifi": 0.3, "midgard": 0.2, "debridge": 0.2, "wormholescan": 0.3, "sarvam": 0.5}
PROVIDER_RETRIES = {"blockscout": 6, "trongrid": 6}  # public, keyless endpoints rate-limit bursts with 429s
RESET_IN_MS = {"blockscout"}  # X-RateLimit-Reset is milliseconds remaining
MAX_RATE_WAIT = 60.0          # a longer 429 lockout fails fast (and trips the breaker) instead of stalling the trace
UNREACHABLE_PAUSE = 300.0     # after 2 connection failures in one call, skip the provider for this long
_blocked_until: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}
_last_call: dict[str, float] = {}
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # short connect timeout: a dead host should fail in seconds; reads may legitimately take longer
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=8), headers={"User-Agent": "BitTrail/0.3 (SIH prototype)"})
    return _client


def cache_key(provider: str, url: str, params: dict | None) -> str:
    raw = provider + "|" + url + "|" + json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _redact(params: dict | None) -> dict:
    return {k: v for k, v in (params or {}).items() if k.lower() not in ("apikey", "api_key")}


async def cached_get(provider: str, url: str, params: dict | None = None, headers: dict | None = None,
                     ttl_seconds: int | None = None, retries: int = 4, json_body: dict | None = None,
                     ok_status: tuple[int, ...] = (200,)) -> dict | list:
    """GET (or POST when json_body is given, e.g. JSON-RPC) through the cache.

    `ok_status`: extra HTTP statuses that are a valid, cacheable answer (e.g. a tracker's 404 "unknown transaction");
    they are stored and returned as {"__http_status": code}.
    """
    key = cache_key(provider, url, {**_redact(params), **({"__body": json_body} if json_body else {})})
    s = settings()
    with SessionLocal() as db:
        row = db.get(ApiCache, key)
        if row is not None:
            fresh = ttl_seconds is None or s.demo_mode or (
                (datetime.now(timezone.utc) - row.fetched_at).total_seconds() < ttl_seconds
            )
            if fresh:
                return row.response
    if s.demo_mode:
        raise AdapterUnavailable(f"demo mode: no cached data for {provider} {url}")

    blocked = _blocked_until.get(provider, 0) - time.monotonic()
    if blocked > 0:  # circuit breaker: a long rate-limit lockout must not stall every address of a trace
        raise AdapterUnavailable(f"{provider} rate limit reached; resets in {blocked / 60:.0f} min")
    lock = _locks.setdefault(provider, asyncio.Lock())
    retries = max(retries, PROVIDER_RETRIES.get(provider, retries))
    delay = 1.0
    last_exc: Exception | None = None
    last_status: int | None = None
    conn_fail = 0
    for _ in range(retries):
        # the lock only spaces request STARTS (free-tier rate limits); requests themselves run concurrently
        async with lock:
            wait = MIN_INTERVAL.get(provider, 0.2) - (time.monotonic() - _last_call.get(provider, 0))
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call[provider] = time.monotonic()
        try:
            if json_body is not None:
                r = await _get_client().post(url, params=params, headers=headers, json=json_body)
            else:
                r = await _get_client().get(url, params=params, headers=headers)
        except httpx.HTTPError as e:
            last_exc = e
            r = None
            if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
                conn_fail += 1
                if conn_fail >= 2:  # host unreachable / blocking us: stop hammering it, let the caller fall back
                    _blocked_until[provider] = time.monotonic() + UNREACHABLE_PAUSE
                    raise AdapterUnavailable(f"{provider} unreachable ({type(e).__name__}); paused "
                                             f"{UNREACHABLE_PAUSE // 60:.0f} min") from None
        if r is not None and (r.status_code == 200 or r.status_code in ok_status):
            try:
                data = r.json() if r.status_code == 200 else {"__http_status": r.status_code}
            except ValueError:
                raise AdapterUnavailable(f"{provider}: non-JSON response ({r.text[:80]!r})") from None
            with SessionLocal() as db:
                row = db.get(ApiCache, key)
                if row is None:
                    db.add(ApiCache(key=key, provider=provider,
                                    request={"url": url, "params": _redact(params), **({"body": json_body} if json_body else {})},
                                    response=data, ttl_seconds=ttl_seconds))
                else:
                    row.response, row.fetched_at = data, datetime.now(timezone.utc)
                db.commit()
            return data
        if r is not None and r.status_code not in (429, 500, 502, 503, 504):
            raise AdapterUnavailable(f"{provider} HTTP {r.status_code}: {r.text[:200]}")
        wait_s = 0.0
        if r is not None:
            last_status = r.status_code
            if r.status_code == 429:
                wait_s = _reset_seconds(provider, r.headers)
                if wait_s > MAX_RATE_WAIT:
                    _blocked_until[provider] = time.monotonic() + wait_s
                    raise AdapterUnavailable(f"{provider} rate limit reached; resets in {wait_s / 60:.0f} min")
        await asyncio.sleep(max(delay, wait_s))
        delay *= 2
    raise AdapterUnavailable(f"{provider} unavailable after {retries} tries: "
                             + (f"HTTP {last_status}" if last_status else str(last_exc)))


def _reset_seconds(provider: str, headers) -> float:
    """Seconds until a 429 lifts: Retry-After (seconds) or X-RateLimit-Reset (Blockscout: milliseconds remaining;
    others: epoch seconds or seconds remaining)."""
    try:
        if headers.get("retry-after"):
            return float(headers["retry-after"])
        v = float(headers.get("x-ratelimit-reset") or 0)
    except ValueError:
        return 0.0
    if v > 1e9:  # epoch seconds
        return max(0.0, v - time.time())
    return v / 1000 if provider in RESET_IN_MS else v
