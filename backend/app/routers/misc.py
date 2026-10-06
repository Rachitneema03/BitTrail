from __future__ import annotations

import asyncio
import hashlib
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters import bridges, chain_status
from ..audit import GENESIS, audit
from ..auth import DEMO_PASSWORD, DEMO_USERS, current_user, make_token, require, user_from_token, verify_password
from ..config import settings
from ..db import SessionLocal, get_db
from ..labels.index import label_index
from ..models import (Alert, AuditLog, Candidate, Case, CaseLink, Label, Request as Req, TraceJob, User, Vasp,
                      WatchItem, now)
from ..watch.poller import check_item
from .cases import CaseIn, create_case
from ..jobs import start_trace

router = APIRouter(prefix="/api/v1", tags=["misc"])
TRACKER_NAMES = {"lifi": "LI.FI", "thorchain": "THORChain Midgard", "debridge": "deBridge DLN", "wormhole": "Wormholescan"}


class LoginIn(BaseModel):
    email: str
    password: str


@router.get("/health")
def health(db: Session = Depends(get_db)):
    s = settings()
    st = chain_status()
    return {"status": "ok", "demo_mode": s.demo_mode, "labels": db.execute(select(func.count(Label.id))).scalar(),
            "labelled_addresses": len(label_index()),
            "chains": {c: v["live"] for c, v in st.items()},
            "chain_sources": st,
            "ai": {"provider": "Sarvam AI", "configured": bool(s.sarvam_api_key)},
            "bridge_tracker": ", ".join(TRACKER_NAMES[p] for p in bridges.enabled()) or None,
            "version": s.app_version,
            "db": "sqlite" if s.is_sqlite else "postgres"}


@router.post("/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.email == data.email.lower().strip())).scalar()
    if not u or not verify_password(data.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"token": make_token(u), "user": me_dict(u, db)}


@router.get("/auth/demo-users")
def demo_users():
    # Served from the seed constant, not the DB: the login page must list demo roles even while the
    # connection pool is busy (startup traces, watch poller) or the database is briefly unreachable.
    return {"password": DEMO_PASSWORD,
            "users": [{"email": email, "name": name, "role": role} for name, email, role in DEMO_USERS]}


def me_dict(u: User, db: Session) -> dict:
    vasp = db.get(Vasp, u.vasp_id) if u.vasp_id else None
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "vasp_id": u.vasp_id,
            "vasp_name": vasp.name if vasp else None}


@router.get("/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_dict(user, db)


@router.get("/alerts")
def alerts(db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    rows = db.execute(select(Alert).order_by(Alert.created_at.desc()).limit(200)).scalars().all()
    cases = {c.id: c.case_no for c in db.execute(select(Case)).scalars()}
    return [{"id": a.id, "case_id": a.case_id, "case_no": cases.get(a.case_id), "type": a.type, "severity": a.severity,
             "message": a.message, "data": a.data, "read": a.read, "created_at": a.created_at} for a in rows]


@router.post("/alerts/{alert_id}/read")
def mark_read(alert_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    a = db.get(Alert, alert_id)
    if a:
        a.read = True
        audit(db, "alert.read", "alert", alert_id, user.id, {"type": a.type})
        db.commit()
    return {"ok": True}


@router.get("/alerts/stream")
async def alert_stream(token: str, request: Request):
    """Server-sent events: every new alert (watch-list movement, freeze window, high-risk wallet, case link) is pushed
    to open browsers within ~2 s. EventSource cannot send headers, so the JWT comes as a query parameter."""
    with SessionLocal() as db:
        user_from_token(token, db)

    async def events():
        since = now()
        last_ping = time.monotonic()
        yield "retry: 5000\n\n"
        while not await request.is_disconnected():
            with SessionLocal() as db:
                rows = db.execute(select(Alert).where(Alert.created_at > since).order_by(Alert.created_at)).scalars().all()
                nos = {c.id: c.case_no for c in db.execute(select(Case).where(Case.id.in_({a.case_id for a in rows}))).scalars()} if rows else {}
            for a in rows:
                since = max(since, a.created_at)
                payload = {"id": a.id, "case_id": a.case_id, "case_no": nos.get(a.case_id), "type": a.type,
                           "severity": a.severity, "message": a.message, "created_at": a.created_at.isoformat()}
                yield f"event: alert\ndata: {json.dumps(payload)}\n\n"
            if time.monotonic() - last_ping > 15:
                last_ping = time.monotonic()
                yield ": ping\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/audit")
def audit_log(limit: int = 200, db: Session = Depends(get_db), user: User = Depends(require("analyst"))):
    """Append-only, hash-chained audit trail (I4C analysts only)."""
    users = {u.id: u.name for u in db.execute(select(User)).scalars()}
    rows = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))).scalars().all()
    return [{"id": r.id, "at": r.at, "user": users.get(r.user_id, "system" if not r.user_id else r.user_id),
             "action": r.action, "entity": r.entity, "entity_id": r.entity_id, "data": r.data, "hash": r.hash,
             "prev_hash": r.prev_hash} for r in rows]


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(get_db), user: User = Depends(require("analyst"))):
    """Recompute the whole hash chain: any edited, deleted or re-ordered row breaks it."""
    prev, n = GENESIS, 0
    for r in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        payload = json.dumps({"at": r.at.isoformat(), "user": r.user_id, "action": r.action, "entity": r.entity,
                              "id": r.entity_id, "data": r.data or {}}, sort_keys=True, separators=(",", ":"), default=str)
        if r.prev_hash != prev or hashlib.sha256((prev + payload).encode()).hexdigest() != r.hash:
            return {"ok": False, "rows_checked": n, "first_bad_id": r.id, "head": prev}
        prev, n = r.hash, n + 1
    return {"ok": True, "rows_checked": n, "head": prev}


@router.get("/cases/{case_id}/watch")
def watch_items(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    return [{"id": w.id, "chain": w.chain, "address": w.address, "reason": w.reason, "entity": w.entity,
             "active": w.active, "last_checked_at": w.last_checked_at}
            for w in db.execute(select(WatchItem).where(WatchItem.case_id == case_id)).scalars()]


@router.post("/watch/{item_id}/check")
async def check_now(item_id: str, user: User = Depends(require("io", "analyst"))):
    return {"new_transfers": await check_item(item_id)}


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    cases = db.execute(select(Case)).scalars().all()
    done_jobs = db.execute(select(TraceJob).where(TraceJob.status == "done")).scalars().all()
    latest: dict[str, TraceJob] = {}
    for j in done_jobs:
        if j.case_id not in latest or j.created_at > latest[j.case_id].created_at:
            latest[j.case_id] = j
    traced = sum((j.progress or {}).get("seed_out_usd", 0) for j in latest.values())
    cands = db.execute(select(Candidate).where(Candidate.job_id.in_([j.id for j in latest.values()]),
                                               Candidate.role == "off_ramp")).scalars().all() if latest else []
    top: dict[str, dict] = {}
    for c in cands:
        t = top.setdefault(c.vasp_name, {"vasp": c.vasp_name, "cases": set(), "value_usd": 0.0})
        t["cases"].add(c.case_id)
        t["value_usd"] += c.value_usd
    top_list = sorted(({"vasp": v["vasp"], "cases": len(v["cases"]), "value_usd": round(v["value_usd"], 2)} for v in top.values()),
                      key=lambda x: -x["value_usd"])[:8]
    secs = [(j.progress or {}).get("seconds") for j in latest.values() if (j.progress or {}).get("seconds")]
    chains: dict[str, int] = {}
    for j in latest.values():
        for ch in (j.analysis or {}).get("chains") or []:
            chains[ch] = chains.get(ch, 0) + 1
    hops = [h for j in latest.values() for h in (j.analysis or {}).get("crosschain") or []]
    return {
        "cases": len(cases),
        "attributed": sum(1 for c in cases if c.status in ("attributed", "request_sent", "closed")),
        "traced_usd": round(traced, 2),
        "median_trace_seconds": sorted(secs)[len(secs) // 2] if secs else None,
        "links": db.execute(select(func.count(CaseLink.id))).scalar(),
        "requests_sent": db.execute(select(func.count(Req.id)).where(Req.status.notin_(("draft", "pending_approval")))).scalar(),
        "requests_confirmed": db.execute(select(func.count(Req.id)).where(Req.status == "confirmed")).scalar(),
        "unread_alerts": db.execute(select(func.count(Alert.id)).where(Alert.read.is_(False))).scalar(),
        "verified_labels": db.execute(select(func.count(Label.id)).where(Label.source == "vasp_confirmation",
                                                                         Label.negative.is_(False))).scalar(),
        "top_vasps": top_list,
        "chains": chains,
        "crosschain_hops": len(hops),
        "crosschain_routes": sorted({f"{h['from_chain']}->{h['to_chain']} via {h.get('tool') or h['provider']}" for h in hops}),
    }


@router.get("/vasps")
def vasps(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [{k: getattr(v, k) for k in ("id", "name", "kind", "country", "fiu_ind_registered", "on_sahyog", "status_source")}
            for v in db.execute(select(Vasp).order_by(Vasp.name)).scalars()]


@router.post("/sahyog/webhook")
async def sahyog_webhook(data: CaseIn, db: Session = Depends(get_db), user: User = Depends(require("analyst"))):
    """Integration stub: Sahyog pushes a case; BitTrail creates it and starts tracing."""
    case = create_case(db, data, user.id)
    return {"id": case.id, "case_no": case.case_no, "job_id": start_trace(case.id, user.id)}
