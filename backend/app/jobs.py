"""Trace job lifecycle: queued -> running -> done | failed (docs/architecture.md §2)."""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select

from .adapters import AdapterUnavailable, get_adapter
from .audit import audit
from .config import heuristics, settings
from .crosscase import update_links
from .db import SessionLocal
from .engine.classify import short
from .engine.model import TraceParams
from .engine.score import score
from .engine.trace import trace
from .labels.index import label_index
from .labels.registry import actionability
from .models import Alert, Candidate, Case, CaseWallet, TraceEdge, TraceJob, TraceNode, Vasp, WatchItem, now

log = logging.getLogger("bittrail.jobs")
_tasks: set[asyncio.Task] = set()


def default_params() -> TraceParams:
    s = settings()
    return TraceParams(s.trace_max_depth, s.trace_fanout, s.trace_min_usd, s.trace_max_edges,
                       s.trace_window_days, s.trace_back_depth)


def start_trace(case_id: str, user_id: str | None) -> str:
    with SessionLocal() as db:
        p = default_params()
        job = TraceJob(case_id=case_id, status="queued", params=p.__dict__, progress={"message": "Queued"})
        db.add(job)
        case = db.get(Case, case_id)
        case.status = "tracing"
        audit(db, "trace.start", "trace_job", job.id, user_id, {"case_id": case_id, "params": p.__dict__})
        db.commit()
        job_id = job.id
    t = asyncio.create_task(run_job(job_id))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return job_id


async def run_job(job_id: str) -> None:
    t0 = time.monotonic()
    with SessionLocal() as db:
        job = db.get(TraceJob, job_id)
        case = db.get(Case, job.case_id)
        wallets = db.execute(select(CaseWallet).where(CaseWallet.case_id == case.id)).scalars().all()
        job.status, job.started_at = "running", now()
        job.progress = {"message": "Tracing…", "nodes": 0, "edges": 0}
        db.commit()
        seeds = [(w.chain, w.address) for w in wallets]
        fraud_time = case.fraud_time
        params = TraceParams(**job.params)
        vasps = {v.name: v for v in db.execute(select(Vasp)).scalars()}

    last = [0.0]

    async def progress(p: dict) -> None:
        if time.monotonic() - last[0] < 0.5:
            return
        last[0] = time.monotonic()
        with SessionLocal() as db:
            j = db.get(TraceJob, job_id)
            j.progress = {**p, "message": f"Depth {p['depth']} · {p['nodes']} addresses · {p['edges']} links"}
            db.commit()

    try:
        cfg = heuristics()
        res = await trace(seeds, fraud_time, params, label_index(), get_adapter, cfg, progress)
        drafts = score(res, fraud_time, cfg, lambda e: actionability(vasps.get(e)))

        heights: dict = {}
        for chain in {c for c, _ in seeds}:
            try:
                heights[chain] = await get_adapter(chain).chain_height()
            except AdapterUnavailable:
                heights[chain] = None

        for d in drafts:
            if d.role != "off_ramp":
                d.funds_status = "n/a"
                continue
            if d.address_kind == "vasp_deposit":
                try:
                    info = await get_adapter(d.chain).get_info(d.address)
                    bal = info.balance_usd or 0
                    d.funds_status = "at_deposit" if bal >= 1 else "swept"
                    d.signals["deposit_balance_usd"] = round(bal, 2)
                except AdapterUnavailable:
                    d.funds_status = "unknown"
            else:
                d.funds_status = "at_exchange"

        with SessionLocal() as db:
            job = db.get(TraceJob, job_id)
            case = db.get(Case, job.case_id)
            for n in res.nodes.values():
                db.add(TraceNode(job_id=job_id, chain=n.chain, address=n.address, kind=n.kind, depth=n.depth,
                                 value_share=round(n.value_share, 6), value_usd=n.value_usd, entity=n.entity,
                                 label_source=n.label_source, label_tier=n.label_tier, flags=sorted(n.flags),
                                 reasons=n.reasons, stats={**n.stats, "arrival": n.arrival.isoformat() if n.arrival else None,
                                                           "parent": n.parent}))
            for e in res.edges.values():
                db.add(TraceEdge(job_id=job_id, chain=e.chain, from_address=e.frm, to_address=e.to,
                                 asset="/".join(sorted(e.assets)), amount_usd=round(e.amount_usd, 2),
                                 value_share=round(e.value_share, 6), tx_hashes=e.tx_hashes, tx_count=e.tx_count,
                                 first_ts=e.first_ts, block=e.block, direction=e.direction))
            for d in drafts:
                db.add(Candidate(job_id=job_id, case_id=case.id, vasp_id=vasps[d.vasp_name].id if d.vasp_name in vasps else None,
                                 vasp_name=d.vasp_name, role=d.role, chain=d.chain, address=d.address,
                                 address_kind=d.address_kind, hops=d.hops, value_share=d.value_share,
                                 value_usd=d.value_usd, confidence=d.confidence, actionability=d.actionability,
                                 rank_score=d.rank_score, funds_status=d.funds_status, signals=d.signals,
                                 reasons=d.reasons, evidence_tx=d.evidence_tx, path=d.path))
            db.flush()
            update_links(db, case, job_id, res)
            _alerts_and_watch(db, case, drafts, res)
            off = [d for d in drafts if d.role == "off_ramp"]
            case.status = "attributed" if off else "open"
            job.chain_heights = heights
            job.status, job.finished_at = "done", now()
            job.progress = {"message": "Done", "nodes": len(res.nodes), "edges": len(res.edges),
                            "candidates": len(drafts), "seconds": round(time.monotonic() - t0, 1), "notes": res.notes,
                            "seed_out_usd": round(res.seed_out_usd, 2)}
            audit(db, "trace.done", "trace_job", job_id, None,
                  {"nodes": len(res.nodes), "edges": len(res.edges), "candidates": len(drafts)})
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("trace job failed")
        with SessionLocal() as db:
            job = db.get(TraceJob, job_id)
            job.status, job.finished_at, job.error = "failed", now(), str(e)[:500]
            case = db.get(Case, job.case_id)
            case.status = "open"
            db.commit()


def _alerts_and_watch(db, case: Case, drafts, res) -> None:
    for d in drafts:
        if d.role == "off_ramp" and d.address_kind == "vasp_deposit":
            db.add(WatchItem(case_id=case.id, chain=d.chain, address=d.address, reason="deposit_hold", entity=d.vasp_name))
            if d.funds_status == "at_deposit":
                bal = d.signals.get("deposit_balance_usd", 0)
                db.add(Alert(case_id=case.id, type="freeze_window", severity="high",
                             message=f"Freeze window open: ${bal:,.0f} still at {d.vasp_name} deposit address "
                                     f"{short(d.address)}. Send a freeze request now.",
                             data={"address": d.address, "vasp": d.vasp_name, "balance_usd": bal}))
    for n in res.nodes.values():
        if "holds_funds" in n.flags and n.depth > 0 and n.value_share >= 0.05:
            db.add(WatchItem(case_id=case.id, chain=n.chain, address=n.address, reason="private_endpoint"))
        if "sanctioned" in n.flags:
            db.add(Alert(case_id=case.id, type="sanctioned_hit", severity="medium",
                         message=f"Trail touches an OFAC-sanctioned address {short(n.address)}",
                         data={"address": n.address, "chain": n.chain}))
    if not any(d.role == "off_ramp" for d in drafts):
        db.add(Alert(case_id=case.id, type="no_vasp", severity="medium",
                     message="No VASP reached within trace limits. Funds may sit in private wallets: watch-list armed.",
                     data={}))
