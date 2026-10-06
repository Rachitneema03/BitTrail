from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import graphstore
from ..adapters import detect_chain, normalize_address
from ..audit import audit
from ..auth import current_user, require
from ..db import get_db
from ..jobs import start_trace
from ..models import Alert, Candidate, Case, CaseLink, CaseWallet, TraceEdge, TraceJob, TraceNode, User

router = APIRouter(prefix="/api/v1", tags=["cases"])
CHAINS = {"tron", "ethereum", "polygon", "bsc", "bitcoin", "solana"}


class WalletIn(BaseModel):
    address: str
    chain: str | None = None
    victim_tx_hash: str | None = None


class CaseIn(BaseModel):
    title: str | None = None
    fir_no: str = Field(min_length=1)
    ncrp_id: str | None = None
    police_station: str | None = None
    state: str | None = None
    fraud_type: str | None = None
    fraud_time: datetime
    amount_inr: float | None = None
    wallets: list[WalletIn] = Field(min_length=1)
    start_trace: bool = True

    @field_validator("fraud_time")
    @classmethod
    def tz(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def create_case(db: Session, data: CaseIn, user_id: str | None, is_demo: bool = False) -> Case:
    wallets = []
    for w in data.wallets:
        chain = w.chain or detect_chain(w.address)
        if chain not in CHAINS:
            raise HTTPException(422, f"Unrecognised address format: {w.address}")
        wallets.append((chain, normalize_address(chain, w.address), w.victim_tx_hash))
    no = (db.execute(select(func.max(Case.case_no))).scalar() or 0) + 1
    case = Case(case_no=no, title=data.title, fir_no=data.fir_no, ncrp_id=data.ncrp_id, police_station=data.police_station,
                state=data.state, fraud_type=data.fraud_type, fraud_time=data.fraud_time, amount_inr=data.amount_inr,
                created_by=user_id, is_demo=is_demo)
    db.add(case)
    db.flush()
    for chain, addr, vtx in dict.fromkeys(wallets):
        db.add(CaseWallet(case_id=case.id, chain=chain, address=addr, victim_tx_hash=vtx))
    audit(db, "case.create", "case", case.id, user_id, {"fir_no": data.fir_no, "wallets": [w[1] for w in wallets]})
    db.commit()
    return case


def case_dict(c: Case, wallets: list[CaseWallet] | None = None) -> dict:
    d = {k: getattr(c, k) for k in ("id", "case_no", "title", "fir_no", "ncrp_id", "police_station", "state", "fraud_type",
                                    "fraud_time", "amount_inr", "status", "is_demo", "created_at")}
    d["monitoring"] = c.monitoring is not False
    if wallets is not None:
        d["wallets"] = [{"chain": w.chain, "address": w.address, "victim_tx_hash": w.victim_tx_hash} for w in wallets]
    return d


def job_dict(j: TraceJob | None) -> dict | None:
    if j is None:
        return None
    return {k: getattr(j, k) for k in ("id", "status", "params", "progress", "chain_heights", "analysis",
                                       "started_at", "finished_at", "error")}


def cand_dict(c: Candidate) -> dict:
    return {k: getattr(c, k) for k in ("id", "vasp_id", "vasp_name", "role", "chain", "address", "address_kind", "hops",
                                       "value_share", "value_usd", "confidence", "actionability", "rank_score",
                                       "funds_status", "signals", "reasons", "evidence_tx", "path", "explain")}


def latest_job(db: Session, case_id: str, done_only: bool = False) -> TraceJob | None:
    q = select(TraceJob).where(TraceJob.case_id == case_id)
    if done_only:
        q = q.where(TraceJob.status == "done")
    return db.execute(q.order_by(TraceJob.created_at.desc()).limit(1)).scalar()


@router.post("/cases")
async def create(data: CaseIn, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    case = create_case(db, data, user.id)
    job_id = start_trace(case.id, user.id) if data.start_trace else None
    return {"id": case.id, "case_no": case.case_no, "job_id": job_id}


@router.get("/cases")
def list_cases(db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    cases = db.execute(select(Case).order_by(Case.case_no.desc())).scalars().all()
    out = []
    for c in cases:
        offs = db.execute(select(Candidate).where(Candidate.case_id == c.id, Candidate.role == "off_ramp",
                                                  Candidate.job_id == select(TraceJob.id).where(TraceJob.case_id == c.id, TraceJob.status == "done")
                                                  .order_by(TraceJob.created_at.desc()).limit(1).scalar_subquery())
                          .order_by(Candidate.rank_score.desc())).scalars().all()
        wallets = db.execute(select(CaseWallet).where(CaseWallet.case_id == c.id)).scalars().all()
        links = db.execute(select(func.count(CaseLink.id)).where((CaseLink.case_a == c.id) | (CaseLink.case_b == c.id))).scalar()
        d = case_dict(c, wallets)
        d["top_vasp"] = cand_dict(offs[0]) if offs else None
        d["vasps"] = list(dict.fromkeys(x.vasp_name for x in offs))
        d["links"] = links
        out.append(d)
    return out


@router.get("/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    wallets = db.execute(select(CaseWallet).where(CaseWallet.case_id == c.id)).scalars().all()
    job = latest_job(db, c.id)
    done = latest_job(db, c.id, done_only=True)
    cands = db.execute(select(Candidate).where(Candidate.job_id == done.id).order_by(Candidate.role, Candidate.rank_score.desc())
                       ).scalars().all() if done else []
    links = db.execute(select(CaseLink).where((CaseLink.case_a == c.id) | (CaseLink.case_b == c.id))).scalars().all()
    link_out = []
    for l in links:
        peer = db.get(Case, l.case_b if l.case_a == c.id else l.case_a)
        link_out.append({"peer_case_id": peer.id, "peer_case_no": peer.case_no, "peer_state": peer.state,
                         "peer_fir": peer.fir_no, "chain": l.chain, "address": l.address, "kind": l.kind, "entity": l.entity})
    alerts = db.execute(select(Alert).where(Alert.case_id == c.id).order_by(Alert.created_at.desc())).scalars().all()
    return {**case_dict(c, wallets), "job": job_dict(job), "done_job": job_dict(done),
            "candidates": [cand_dict(x) for x in cands], "links": link_out,
            "alerts": [{k: getattr(a, k) for k in ("id", "type", "severity", "message", "data", "read", "created_at")} for a in alerts]}


@router.post("/cases/{case_id}/trace")
async def retrace(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    if not db.get(Case, case_id):
        raise HTTPException(404, "Case not found")
    return {"job_id": start_trace(case_id, user.id)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    j = db.get(TraceJob, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return job_dict(j)


@router.get("/cases/{case_id}/graph/export")
def export_graph(case_id: str, format: str = "graphml", db: Session = Depends(get_db),
                 user: User = Depends(require("io", "analyst"))):
    """Trace graph as GraphML (Gephi / NetworkX), Cypher (Neo4j) or JSON."""
    c = db.get(Case, case_id)
    job = latest_job(db, case_id, done_only=True)
    if not c or not job:
        raise HTTPException(404, "No completed trace for this case")
    nodes, edges = graphstore.load(db, job)
    name = f"bittrail-case-{c.case_no}"
    if format == "cypher":
        body, mt, ext = graphstore.cypher_script(c, nodes, edges), "text/plain", "cypher"
    elif format == "json":
        body, mt, ext = json.dumps(graph(case_id, db, user), default=str, indent=1), "application/json", "json"
    else:
        body, mt, ext = graphstore.graphml(c, nodes, edges), "application/xml", "graphml"
    audit(db, "graph.export", "case", case_id, user.id, {"format": ext})
    db.commit()
    return Response(body, media_type=mt, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})


@router.get("/cases/{case_id}/graph")
def graph(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    job = latest_job(db, case_id, done_only=True)
    if not job:
        return {"nodes": [], "edges": [], "job_id": None}
    nodes = db.execute(select(TraceNode).where(TraceNode.job_id == job.id)).scalars().all()
    edges = db.execute(select(TraceEdge).where(TraceEdge.job_id == job.id)).scalars().all()
    return {
        "job_id": job.id,
        "nodes": [{"data": {"id": f"{n.chain}:{n.address}", "address": n.address, "chain": n.chain, "kind": n.kind,
                            "entity": n.entity, "depth": n.depth, "value_share": n.value_share, "value_usd": n.value_usd,
                            "label_source": n.label_source, "label_tier": n.label_tier, "flags": n.flags,
                            "reasons": n.reasons, "stats": n.stats}} for n in nodes],
        "edges": [{"data": {"id": e.id, "source": f"{e.chain}:{e.from_address}", "target": f"{e.to_chain or e.chain}:{e.to_address}",
                            "to_chain": e.to_chain or e.chain,
                            "chain": e.chain, "direction": e.direction, "asset": e.asset, "amount_usd": e.amount_usd,
                            "value_share": e.value_share, "tx_hashes": e.tx_hashes, "tx_count": e.tx_count,
                            "first_ts": e.first_ts}} for e in edges],
    }
