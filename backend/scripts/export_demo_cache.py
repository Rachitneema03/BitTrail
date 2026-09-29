"""Snapshot cached API responses + prices into data/demo_cache.json.gz.

Run after the demo cases have traced once with live APIs. On a fresh deployment the app imports the
snapshot at startup, so demo cases trace offline (and DEMO_MODE=1 works without any API key).
"""
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.config import BACKEND_DIR  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import ApiCache, Price  # noqa: E402

OUT = BACKEND_DIR / "data" / "demo_cache.json.gz"

with SessionLocal() as db:
    rows = [{"key": r.key, "provider": r.provider, "request": r.request, "response": r.response,
             "fetched_at": r.fetched_at.isoformat()} for r in db.execute(select(ApiCache)).scalars()]
    prices = [{"asset": p.asset, "day": p.day, "usd": p.usd} for p in db.execute(select(Price)).scalars()]
OUT.write_bytes(gzip.compress(json.dumps({"api_cache": rows, "prices": prices}).encode()))
print(f"wrote {OUT} ({len(rows)} responses, {len(prices)} prices, {OUT.stat().st_size // 1024} KB)")
