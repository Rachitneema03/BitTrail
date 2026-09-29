"""BitTrail API + static frontend. Run: uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select

from .auth import seed_users
from .config import BACKEND_DIR, settings
from .db import SessionLocal, init_db
from .jobs import start_trace
from .labels.seed import seed_all
from .models import ApiCache, Case, Price
from .routers import cases, misc, reports, requests
from .watch.poller import poll_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bittrail")
DEMO_CASES = BACKEND_DIR / "data" / "demo_cases.json"
DEMO_CACHE = BACKEND_DIR / "data" / "demo_cache.json.gz"


def import_demo_cache() -> None:
    """Load the committed API-response snapshot so demo cases trace offline / without API keys."""
    if not DEMO_CACHE.exists():
        return
    with SessionLocal() as db:
        if db.execute(select(func.count(ApiCache.key))).scalar():
            return
        data = json.loads(gzip.decompress(DEMO_CACHE.read_bytes()))
        for i, r in enumerate(data["api_cache"], 1):
            db.add(ApiCache(key=r["key"], provider=r["provider"], request=r["request"], response=r["response"],
                            fetched_at=datetime.fromisoformat(r["fetched_at"]), ttl_seconds=None))
            if i % 10 == 0:
                db.commit()
        for p in data.get("prices", []):
            if not db.get(Price, {"asset": p["asset"], "day": p["day"]}):
                db.add(Price(**p))
        db.commit()
        log.info("imported demo cache: %d responses", len(data["api_cache"]))


def seed_demo_cases() -> list[str]:
    from .routers.cases import CaseIn, create_case

    if not DEMO_CASES.exists():
        return []
    with SessionLocal() as db:
        if db.execute(select(func.count(Case.id))).scalar():
            return []
        ids = []
        for c in json.loads(DEMO_CASES.read_text(encoding="utf-8"))["cases"]:
            ids.append(create_case(db, CaseIn(**c), None, is_demo=True).id)
        return ids


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_all()
    with SessionLocal() as db:
        seed_users(db)
    import_demo_cache()
    for case_id in seed_demo_cases():
        start_trace(case_id, None)
        await asyncio.sleep(0)  # traces run sequentially enough via per-provider rate limits
    poller = asyncio.create_task(poll_forever())
    yield
    poller.cancel()


app = FastAPI(title="BitTrail API", version="0.1.0", lifespan=lifespan,
              description="Automated attribution of unknown crypto wallets to the nearest VASP (SIH 2026 · PS 26182 · team TrackSense)")
app.add_middleware(CORSMiddleware, allow_origins=settings().cors_origins.split(","), allow_methods=["*"], allow_headers=["*"])
for r in (cases.router, reports.router, requests.router, misc.router):
    app.include_router(r)

DIST = Path(settings().frontend_dist)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str, request: Request):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    target = DIST / full_path
    if full_path and target.is_file():
        return FileResponse(target)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Frontend not built. Run `npm run build` in frontend/ or use the Vite dev server."}, 404)
