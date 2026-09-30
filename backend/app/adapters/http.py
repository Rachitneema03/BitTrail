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
MIN_INTERVAL = {"trongrid": 0.4, "etherscan": 0.25, "bscapi": 0.25, "mempool": 0.3, "binance": 0.1,
                "solana": 0.6, "lifi": 0.3, "sarvam": 0.5}
_locks: dict[str, asyncio.Lock] = {}
_last_call: dict[str, float] = {}
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30, headers={"User-Agent": "BitTrail/0.1 (SIH prototype)"})
    return _client


def cache_key(provider: str, url: str, params: dict | None) -> str:
    raw = provider + "|" + url + "|" + json.dumps(params or {}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _redact(params: dict | None) -> dict:
    return {k: v for k, v in (params or {}).items() if k.lower() not in ("apikey", "api_key")}


async def cached_get(provider: str, url: str, params: dict | None = None, headers: dict | None = None,
                     ttl_seconds: int | None = None, retries: int = 4, json_body: dict | None = None) -> dict | list:
    """GET (or POST when json_body is given, e.g. JSON-RPC) through the cache."""
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

    lock = _locks.setdefault(provider, asyncio.Lock())
    delay = 1.0
    last_exc: Exception | None = None
    for _ in range(retries):
        async with lock:
            wait = MIN_INTERVAL.get(provider, 0.2) - (time.monotonic() - _last_call.get(provider, 0))
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                if json_body is not None:
                    r = await _get_client().post(url, params=params, headers=headers, json=json_body)
                else:
                    r = await _get_client().get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                last_exc = e
                r = None
            _last_call[provider] = time.monotonic()
        if r is not None and r.status_code == 200:
            data = r.json()
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
        await asyncio.sleep(delay)
        delay *= 2
    raise AdapterUnavailable(f"{provider} unavailable after retries: {last_exc}")
