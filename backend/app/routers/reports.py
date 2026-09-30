from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth import current_user, require
from ..db import get_db
from ..models import Candidate, Case, Report, TraceEdge, TraceJob, TraceNode, User
from ..reports.manifest import build_manifest, sha256
from ..reports.pdf import render
from ..timeline import build_timeline
from .cases import cand_dict, latest_job

router = APIRouter(prefix="/api/v1", tags=["reports"])


@router.post("/cases/{case_id}/reports")
def create_report(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    case = db.get(Case, case_id)
    job = latest_job(db, case_id, done_only=True) if case else None
    if not job:
        raise HTTPException(409, "No completed trace for this case")
    manifest = build_manifest(db, case, job)
    rep = Report(case_id=case.id, job_id=job.id, manifest=manifest, sha256=sha256(manifest), created_by=user.id)
    db.add(rep)
    db.flush()
    audit(db, "report.generate", "report", rep.id, user.id, {"sha256": rep.sha256, "case_id": case.id})
    db.commit()
    return {"id": rep.id, "sha256": rep.sha256, "created_at": rep.created_at}


@router.get("/cases/{case_id}/reports")
def list_reports(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    rows = db.execute(select(Report).where(Report.case_id == case_id).order_by(Report.created_at.desc())).scalars().all()
    return [{"id": r.id, "sha256": r.sha256, "created_at": r.created_at, "job_id": r.job_id} for r in rows]


@router.get("/reports/{report_id}/manifest")
def get_manifest(report_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return {"sha256": r.sha256, "recomputed_sha256": sha256(r.manifest), "manifest": r.manifest}


@router.get("/reports/{report_id}.pdf")
def get_pdf(report_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    case = db.get(Case, r.case_id)
    cands = db.execute(select(Candidate).where(Candidate.job_id == r.job_id)
                       .order_by(Candidate.role, Candidate.rank_score.desc())).scalars().all()
    nodes = {n.address: {"kind": n.kind, "entity": n.entity}
             for n in db.execute(select(TraceNode).where(TraceNode.job_id == r.job_id)).scalars()}
    edges = [{"from": e.from_address, "to": e.to_address, "asset": e.asset, "amount_usd": e.amount_usd,
              "tx_count": e.tx_count, "value_share": e.value_share, "direction": e.direction, "tx_hashes": e.tx_hashes}
             for e in db.execute(select(TraceEdge).where(TraceEdge.job_id == r.job_id).order_by(TraceEdge.first_ts)).scalars()]
    case_d = {k: getattr(case, k) for k in ("case_no", "fir_no", "ncrp_id", "police_station", "state", "fraud_type", "fraud_time")}
    job = db.get(TraceJob, r.job_id)
    analysis = (job.analysis if job else None) or {}
    narrative = (analysis.get("narratives") or {}).get("en-IN")
    pdf = render(r.manifest, r.sha256, case_d, [cand_dict(c) for c in cands], nodes, edges,
                 analysis=analysis, timeline=build_timeline(db, case), narrative=narrative)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="BitTrail_Case{case.case_no}_{r.sha256[:8]}.pdf"'})
