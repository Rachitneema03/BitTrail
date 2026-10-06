"""Investigation timeline: on-chain movements + investigation events, in time order."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine.classify import short
from .models import Alert, Case, Report, Request, TraceEdge, TraceJob, TraceNode, VaspReply

DIRECTION_TITLE = {"forward": "Transfer", "sweep": "Swept to exchange hot wallet", "backward": "Funding inflow (on-ramp)",
                   "bridge": "Bridged across chains", "mix": "Entered a CoinJoin / mixer (trail stops)"}


def build_timeline(db: Session, case: Case, limit_onchain: int = 200) -> list[dict]:
    ev: list[dict] = [{"ts": case.fraud_time, "kind": "case", "title": f"Fraud reported (FIR {case.fir_no})",
                       "detail": f"{case.fraud_type or 'Cyber fraud'} · {case.police_station or ''} {case.state or ''}".strip()},
                      {"ts": case.created_at, "kind": "system", "title": "Case opened in BitTrail",
                       "detail": f"Case #{case.case_no}"}]
    jobs = db.execute(select(TraceJob).where(TraceJob.case_id == case.id).order_by(TraceJob.created_at)).scalars().all()
    for j in jobs:
        if j.finished_at and j.status == "done":
            risk = (j.analysis or {}).get("risk") or {}
            ev.append({"ts": j.finished_at, "kind": "system", "title": "Trace completed",
                       "detail": f"{(j.progress or {}).get('nodes')} addresses · {(j.progress or {}).get('edges')} links · "
                                 f"{(j.progress or {}).get('seconds')} s" + (f" · risk {risk.get('level', '').upper()}" if risk else "")})
        elif j.status == "failed":
            ev.append({"ts": j.finished_at or j.created_at, "kind": "system", "title": "Trace failed", "detail": j.error or ""})
    done = next((j for j in reversed(jobs) if j.status == "done"), None)
    if done:
        nodes = {(n.chain, n.address): n for n in db.execute(select(TraceNode).where(TraceNode.job_id == done.id)).scalars()}
        edges = db.execute(select(TraceEdge).where(TraceEdge.job_id == done.id, TraceEdge.first_ts.is_not(None))
                           .order_by(TraceEdge.first_ts).limit(limit_onchain)).scalars().all()

        def name(chain, addr):
            n = nodes.get((chain, addr))
            if n is None:
                return short(addr)
            return f"{n.entity} {n.kind.replace('vasp_', '')}" if n.entity else ("suspect" if n.kind == "suspect" else short(addr))

        for e in edges:
            to_chain = e.to_chain or e.chain
            ev.append({"ts": e.first_ts, "kind": "onchain", "title": DIRECTION_TITLE.get(e.direction, "Transfer"),
                       "detail": f"${e.amount_usd:,.0f} {e.asset} · {name(e.chain, e.from_address)} → {name(to_chain, e.to_address)}"
                                 + (f" ({e.chain} → {to_chain})" if to_chain != e.chain else ""),
                       "data": {"chain": e.chain, "to_chain": to_chain, "direction": e.direction, "tx": e.tx_hashes[:3],
                                "tx_count": e.tx_count, "amount_usd": e.amount_usd, "from": e.from_address, "to": e.to_address,
                                "edge_id": e.id}})
    for a in db.execute(select(Alert).where(Alert.case_id == case.id)).scalars():
        ev.append({"ts": a.created_at, "kind": "alert", "title": a.type.replace("_", " ").capitalize(), "detail": a.message,
                   "data": {"severity": a.severity}})
    for r in db.execute(select(Report).where(Report.case_id == case.id)).scalars():
        ev.append({"ts": r.created_at, "kind": "evidence", "title": "Evidence report sealed", "detail": f"SHA-256 {r.sha256[:16]}…"})
    for q in db.execute(select(Request).where(Request.case_id == case.id)).scalars():
        ev.append({"ts": q.created_at, "kind": "legal", "title": f"Notice drafted to {q.vasp_name}", "detail": q.legal_basis})
        if q.sent_at:
            ev.append({"ts": q.sent_at, "kind": "legal", "title": f"Notice sent via Sahyog to {q.vasp_name}", "detail": q.sahyog_ref or ""})
        rep = db.execute(select(VaspReply).where(VaspReply.request_id == q.id)).scalar()
        if rep:
            ev.append({"ts": rep.replied_at, "kind": "legal", "title": f"{q.vasp_name} replied: {rep.outcome}",
                       "detail": (f"account {rep.account_ref}" if rep.account_ref else "")
                                 + (f" · ${rep.frozen_amount_usd:,.0f} frozen" if rep.frozen_amount_usd else "")})
    ev.sort(key=lambda e: e["ts"])
    for e in ev:
        e["ts"] = e["ts"].isoformat()
    return ev
