"""Drafted Sahyog notices, mock routing, simulated VASP inbox and the labels flywheel."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import audit
from ..auth import current_user, require
from ..config import heuristics
from ..db import get_db
from ..engine.score import noisy_or
from ..labels.index import invalidate
from ..models import Candidate, Case, CaseWallet, Label, Report, Request, User, Vasp, VaspReply, now
from ..notices.templates import render_notice

router = APIRouter(prefix="/api/v1", tags=["requests"])


class RequestIn(BaseModel):
    candidate_id: str
    type: str = "disclosure_and_freeze"


class ReplyIn(BaseModel):
    outcome: str  # confirmed | denied
    account_ref: str | None = None
    frozen_amount_usd: float | None = None
    note: str | None = None


def req_dict(r: Request, db: Session) -> dict:
    case = db.get(Case, r.case_id)
    reply = db.execute(select(VaspReply).where(VaspReply.request_id == r.id)).scalar()
    return {"id": r.id, "case_id": r.case_id, "case_no": case.case_no, "fir_no": case.fir_no, "state": case.state,
            "vasp_name": r.vasp_name, "vasp_id": r.vasp_id, "type": r.type, "legal_basis": r.legal_basis, "chain": r.chain,
            "addresses": r.addresses, "body_md": r.body_md, "status": r.status, "sahyog_ref": r.sahyog_ref,
            "report_id": r.report_id, "created_at": r.created_at, "sent_at": r.sent_at,
            "reply": {"outcome": reply.outcome, "account_ref": reply.account_ref, "frozen_amount_usd": reply.frozen_amount_usd,
                      "note": reply.note, "replied_at": reply.replied_at} if reply else None}


@router.post("/cases/{case_id}/requests")
def draft(case_id: str, data: RequestIn, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    if data.type not in ("disclosure", "freeze", "disclosure_and_freeze"):
        raise HTTPException(422, "Invalid request type")
    case = db.get(Case, case_id)
    cand = db.get(Candidate, data.candidate_id)
    if not case or not cand or cand.case_id != case_id:
        raise HTTPException(404, "Case or candidate not found")
    report = db.execute(select(Report).where(Report.case_id == case_id, Report.job_id == cand.job_id)
                        .order_by(Report.created_at.desc())).scalar()
    vasp = db.get(Vasp, cand.vasp_id) if cand.vasp_id else None
    suspect = db.execute(select(CaseWallet.address).where(CaseWallet.case_id == case_id)).scalar()
    body, legal = render_notice(req_type=data.type, case=case, candidate=cand, officer=user.name,
                                contact=(vasp.nodal_contact if vasp and vasp.nodal_contact else f"Nodal Officer, {cand.vasp_name}"),
                                suspect=suspect, sha=report.sha256 if report else None)
    r = Request(case_id=case_id, vasp_id=cand.vasp_id, vasp_name=cand.vasp_name, candidate_id=cand.id, type=data.type,
                legal_basis=legal, chain=cand.chain, addresses=[cand.address], body_md=body,
                report_id=report.id if report else None, status="draft")
    db.add(r)
    db.flush()
    audit(db, "request.draft", "request", r.id, user.id, {"case_id": case_id, "vasp": cand.vasp_name, "type": data.type})
    db.commit()
    return req_dict(r, db)


@router.post("/requests/{req_id}/send")
def send(req_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    r = db.get(Request, req_id)
    if not r:
        raise HTTPException(404, "Request not found")
    if r.status != "draft":
        raise HTTPException(409, f"Request already {r.status}")
    n = db.execute(select(func.count(Request.id)).where(Request.sahyog_ref.is_not(None))).scalar() + 1
    r.status, r.sent_at, r.sahyog_ref = "sent", now(), f"SHG-MOCK-{now().year}-{n:05d}"
    case = db.get(Case, r.case_id)
    case.status = "request_sent"
    audit(db, "request.send", "request", r.id, user.id, {"sahyog_ref": r.sahyog_ref, "vasp": r.vasp_name})
    db.commit()
    return req_dict(r, db)


@router.get("/requests")
def list_requests(db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Request).order_by(Request.created_at.desc())
    if user.role == "vasp":
        q = q.where(Request.vasp_id == user.vasp_id, Request.status != "draft")
    return [req_dict(r, db) for r in db.execute(q).scalars()]


@router.post("/requests/{req_id}/reply")
def reply(req_id: str, data: ReplyIn, db: Session = Depends(get_db), user: User = Depends(require("vasp", "analyst"))):
    r = db.get(Request, req_id)
    if not r or r.status not in ("sent", "acknowledged"):
        raise HTTPException(409, "Request is not awaiting a reply")
    if user.role == "vasp" and user.vasp_id != r.vasp_id:
        raise HTTPException(403, "Not your institution's request")
    if data.outcome not in ("confirmed", "denied"):
        raise HTTPException(422, "outcome must be confirmed or denied")
    db.add(VaspReply(request_id=r.id, outcome=data.outcome, account_ref=data.account_ref,
                     frozen_amount_usd=data.frozen_amount_usd, note=data.note, replied_by=user.id))
    r.status = data.outcome
    updated = flywheel(db, r, data.outcome)
    audit(db, f"reply.{data.outcome}", "request", r.id, user.id, {"vasp": r.vasp_name, "rescored_candidates": updated})
    db.commit()
    return {**req_dict(r, db), "rescored_candidates": updated}


def flywheel(db: Session, r: Request, outcome: str) -> int:
    """A VASP reply becomes a label and re-scores every open candidate on the same address (all cases)."""
    cfg = heuristics()
    confirmed = outcome == "confirmed"
    for addr in r.addresses:
        exists = db.execute(select(Label).where(Label.chain == r.chain, Label.address == addr, Label.type == "vasp_deposit",
                                                Label.source == "vasp_confirmation")).scalar()
        if exists:
            exists.negative, exists.tier = not confirmed, "verified"
        else:
            db.add(Label(chain=r.chain, address=addr, type="vasp_deposit", vasp_id=r.vasp_id, entity_name=r.vasp_name,
                         tier="verified", source="vasp_confirmation", source_ref=r.sahyog_ref, negative=not confirmed))
    invalidate()
    n = 0
    for c in db.execute(select(Candidate).where(Candidate.chain == r.chain, Candidate.address.in_(r.addresses),
                                                Candidate.vasp_name == r.vasp_name)).scalars():
        sig = dict(c.signals)
        pf = sig.pop("path_factor", 1.0)
        extra = {k: sig.pop(k) for k in list(sig) if k not in cfg["weights"]}
        sig["label_tier"] = 1.0 if confirmed else 0.0
        if not confirmed:
            sig.pop("sweep", None)
        old = c.confidence
        c.confidence = noisy_or(sig, cfg["weights"], pf)
        c.rank_score = round(c.value_share * c.confidence * c.actionability, 4)
        c.signals = {**sig, **extra, "path_factor": pf}
        verdict = "Verified" if confirmed else "Denied"
        c.reasons = [*c.reasons, f"{verdict} by {r.vasp_name} via Sahyog reply {r.sahyog_ref}: confidence {old:.2f} → {c.confidence:.2f}"]
        n += 1
    return n
