"""Canonical evidence manifest + SHA-256 (docs/schema.md §6)."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Candidate, Case, CaseWallet, TraceEdge, TraceJob, now


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def sha256(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def build_manifest(db: Session, case: Case, job: TraceJob) -> dict:
    wallets = db.execute(select(CaseWallet).where(CaseWallet.case_id == case.id)).scalars().all()
    edges = db.execute(select(TraceEdge).where(TraceEdge.job_id == job.id)
                       .order_by(TraceEdge.direction, TraceEdge.first_ts)).scalars().all()
    cands = db.execute(select(Candidate).where(Candidate.job_id == job.id)
                       .order_by(Candidate.role, Candidate.rank_score.desc())).scalars().all()
    return {
        "schema": "bittrail.manifest.v1",
        "generated_at": now().isoformat(),
        "case": {"case_no": case.case_no, "fir_no": case.fir_no, "ncrp_id": case.ncrp_id, "state": case.state,
                 "fraud_time": case.fraud_time.isoformat()},
        "trace": {"job_id": job.id, "params": job.params, "chain_heights": job.chain_heights,
                  "started_at": job.started_at.isoformat() if job.started_at else None,
                  "finished_at": job.finished_at.isoformat() if job.finished_at else None},
        "seeds": [f"{w.chain}:{w.address}" for w in wallets],
        "edges": [[e.chain, e.direction, e.from_address, e.to_address, e.asset, round(e.amount_usd, 2), e.tx_count,
                   e.tx_hashes, e.first_ts.isoformat() if e.first_ts else None] for e in edges],
        "candidates": [{"role": c.role, "vasp": c.vasp_name, "chain": c.chain, "address": c.address,
                        "kind": c.address_kind, "hops": c.hops, "value_share": c.value_share,
                        "confidence": c.confidence, "actionability": c.actionability, "rank_score": c.rank_score,
                        "evidence_tx": c.evidence_tx} for c in cands],
    }
