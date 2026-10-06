"""Trace job lifecycle: queued -> running -> done | failed (docs/architecture.md §2)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from sqlalchemy import delete, func, select

from .adapters import AdapterUnavailable, get_adapter, provider_label
from .adapters import bridges
from .alert_rules import get_rules, level_at_least
from .audit import audit
from .config import BACKEND_DIR, heuristics, settings
from .crosscase import update_links
from .db import SessionLocal
from .engine.classify import short
from .engine.model import TraceParams
from .engine.score import score
from .engine.trace import trace
from .engine.typology import analyze, rescore
from .labels.index import label_index
from .labels.registry import actionability
from .models import (Alert, Candidate, Case, CaseLink, CaseWallet, Label, TraceEdge, TraceJob, TraceNode, Vasp,
                     WatchItem, now)

log = logging.getLogger("bittrail.jobs")
_tasks: set[asyncio.Task] = set()


def default_params() -> TraceParams:
    s = settings()
    return TraceParams(s.trace_max_depth, s.trace_fanout, s.trace_min_usd, s.trace_max_edges,
                       s.trace_window_days, s.trace_back_depth)


def ruleset_sha256() -> str:
    return hashlib.sha256((BACKEND_DIR / "config" / "heuristics.yaml").read_bytes()).hexdigest()


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


def make_history(case_id: str):
    """Investigation memory: has this address been tied to this VASP before (verified, or in other cases)?"""
    def history_for(chain: str, address: str, entity: str):
        with SessionLocal() as db:
            v = db.execute(select(Label).where(Label.chain == chain, Label.address == address,
                                               Label.source == "vasp_confirmation", Label.negative.is_(False),
                                               Label.entity_name == entity)).scalars().first()
            if v:
                return 1.0, f"Investigation memory: {entity} confirmed this address earlier via Sahyog ({v.source_ref})"
            n = db.execute(select(func.count(func.distinct(Candidate.case_id))).where(
                Candidate.chain == chain, Candidate.address == address, Candidate.vasp_name == entity,
                Candidate.case_id != case_id)).scalar() or 0
            if n:
                return min(0.9, 0.6 + 0.15 * (n - 1)), \
                    f"Investigation memory: attributed to {entity} in {n} earlier case{'s' if n > 1 else ''}"
        return None
    return history_for


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
        fraud_time, case_id = case.fraud_time, case.id
        params = TraceParams(**job.params)
        vasps = {v.name: v for v in db.execute(select(Vasp)).scalars()}
        prev_job = db.execute(select(TraceJob).where(TraceJob.case_id == case_id, TraceJob.status == "done")
                              .order_by(TraceJob.created_at.desc()).limit(1)).scalar()
        prev = {(c.vasp_name, c.role): c.confidence for c in db.execute(
            select(Candidate).where(Candidate.job_id == prev_job.id)).scalars()} if prev_job else {}

    last = [0.0]

    async def progress(p: dict) -> None:
        if time.monotonic() - last[0] < 0.5:
            return
        last[0] = time.monotonic()
        chains = p.get("chains") or []
        with SessionLocal() as db:
            j = db.get(TraceJob, job_id)
            j.progress = {**p, "message": f"Depth {p['depth']} · {p['nodes']} addresses · {p['edges']} links"
                          + (f" · {len(chains)} chains ({', '.join(chains)})" if len(chains) > 1 else "")
                          + (f" · {p['bridges']} cross-chain hop{'s' if p['bridges'] != 1 else ''}" if p.get("bridges") else "")}
            db.commit()

    try:
        cfg = heuristics()

        async def fallback(chain: str, sender: str, t):
            return await bridges.same_address_match(chain, sender, t, get_adapter, cfg)

        res = await trace(seeds, fraud_time, params, label_index(), get_adapter, cfg, progress,
                          bridge_resolver=bridges.resolve if bridges.enabled() else None, fallback=fallback)
        drafts = score(res, fraud_time, cfg, lambda e: actionability(vasps.get(e)), make_history(case_id))

        heights: dict = {}
        for chain in sorted({n.chain for n in res.nodes.values()}):
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
            rules = get_rules(db)
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
                                 first_ts=e.first_ts, block=e.block, direction=e.direction, to_chain=e.to_chain))
            for d in drafts:
                db.add(Candidate(job_id=job_id, case_id=case.id, vasp_id=vasps[d.vasp_name].id if d.vasp_name in vasps else None,
                                 vasp_name=d.vasp_name, role=d.role, chain=d.chain, address=d.address,
                                 address_kind=d.address_kind, hops=d.hops, value_share=d.value_share,
                                 value_usd=d.value_usd, confidence=d.confidence, actionability=d.actionability,
                                 rank_score=d.rank_score, funds_status=d.funds_status, signals=d.signals,
                                 reasons=d.reasons, evidence_tx=d.evidence_tx, path=d.path, explain=d.explain))
            db.flush()
            new_links = update_links(db, case, job_id, res, alert=rules["new_relationship"])
            links = db.execute(select(func.count(CaseLink.id)).where(
                (CaseLink.case_a == case.id) | (CaseLink.case_b == case.id))).scalar() or 0
            _refresh_peer_risk(db, case.id, new_links, cfg)
            analysis = analyze(res, fraud_time, drafts, links, cfg)
            analysis["integrity"] = integrity(res, heights)
            analysis["crosschain"] = res.crosschain
            # in trail order (seed chain first), not alphabetical: the UI draws it as "TRON -> ETHEREUM"
            analysis["chains"] = list(dict.fromkeys(n.chain for n in sorted(res.nodes.values(), key=lambda n: n.depth)
                                                    if n.depth >= 0))
            analysis["dust"] = res.dust
            job.analysis = analysis
            _alerts_and_watch(db, case, drafts, res, analysis, rules, prev)
            off = [d for d in drafts if d.role == "off_ramp"]
            case.status = "attributed" if off else "open"
            job.chain_heights = heights
            job.status, job.finished_at = "done", now()
            job.progress = {"message": "Done", "nodes": len(res.nodes), "edges": len(res.edges),
                            "candidates": len(drafts), "seconds": round(time.monotonic() - t0, 1), "notes": res.notes,
                            "seed_out_usd": round(res.seed_out_usd, 2), "chains": analysis["chains"],
                            "bridges": len(res.crosschain)}
            audit(db, "trace.done", "trace_job", job_id, None,
                  {"nodes": len(res.nodes), "edges": len(res.edges), "candidates": len(drafts),
                   "chains": analysis["chains"], "cross_chain_hops": len(res.crosschain),
                   "risk": analysis["risk"]["level"], "ruleset_sha256": analysis["integrity"]["ruleset_sha256"]})
            db.commit()
    except Exception as e:  # noqa: BLE001
        log.exception("trace job failed")
        with SessionLocal() as db:
            job = db.get(TraceJob, job_id)
            job.status, job.finished_at, job.error = "failed", now(), str(e)[:500]
            case = db.get(Case, job.case_id)
            case.status = "open"
            db.commit()


def _refresh_peer_risk(db, case_id: str, new_links: list, cfg: dict) -> None:
    """An earlier case that a new case links to gains historical linkage: update its stored risk profile."""
    peers = {l.case_b if l.case_a == case_id else l.case_a for l in new_links}
    for peer in peers:
        job = db.execute(select(TraceJob).where(TraceJob.case_id == peer, TraceJob.status == "done")
                         .order_by(TraceJob.created_at.desc()).limit(1)).scalar()
        if not job or not (job.analysis or {}).get("risk"):
            continue
        n = db.execute(select(func.count(CaseLink.id)).where((CaseLink.case_a == peer) | (CaseLink.case_b == peer))).scalar() or 0
        a = dict(job.analysis)
        axes = [dict(x) for x in a["risk"]["axes"]]
        for x in axes:
            if x["key"] == "historical" and x["score"] < 90:
                x["score"], x["why"] = 90, f"{n} cross-case link(s) (found after this trace)"
        a["risk"] = rescore({**a["risk"], "axes": axes}, cfg)
        job.analysis = a


def integrity(res, heights: dict) -> dict:
    s = settings()
    chains = sorted({n.chain for n in res.nodes.values()})
    edges = list(res.edges.values())
    ts = [e.first_ts for e in edges if e.first_ts]
    blocks: dict[str, list[int]] = {}
    for e in edges:
        if e.block:
            blocks.setdefault(e.chain, []).append(e.block)
    with SessionLocal() as db:
        labels = db.execute(select(func.count(Label.id))).scalar() or 0
    return {
        "engine": "BitTrail", "version": s.app_version, "ruleset_sha256": ruleset_sha256(),
        "labels_loaded": labels, "chains": chains,
        "data_sources": {c: provider_label(c) for c in chains}
        | {"prices": "Binance public daily klines (USDT/USDC = $1)",
           "labels": "Dune Spellbook CEX lists, OFAC SDN (official XML, with programs), curated"}
        | ({"bridges": ", ".join(sorted({h["provider"] for h in res.crosschain}))} if res.crosschain else {}),
        "chain_heights": heights,
        "block_ranges": {c: [min(b), max(b)] for c, b in blocks.items()},
        "time_range": [min(ts).isoformat(), max(ts).isoformat()] if ts else None,
        "transactions_analysed": sum(e.tx_count for e in edges),
        "addresses_analysed": len(res.nodes),
        "llm_used_for_attribution": False,
    }


def _alerts_and_watch(db, case: Case, drafts, res, analysis: dict, rules: dict, prev: dict) -> None:
    # refresh this case's watch-list (re-traces must not duplicate it)
    db.execute(delete(WatchItem).where(WatchItem.case_id == case.id))
    active = case.monitoring is not False
    for w in db.execute(select(CaseWallet).where(CaseWallet.case_id == case.id)).scalars():
        db.add(WatchItem(case_id=case.id, chain=w.chain, address=w.address, reason="suspect_wallet", active=active))
    for d in drafts:
        if d.role == "off_ramp" and d.address_kind == "vasp_deposit":
            db.add(WatchItem(case_id=case.id, chain=d.chain, address=d.address, reason="deposit_hold",
                             entity=d.vasp_name, active=active))
            if d.funds_status == "at_deposit":
                bal = d.signals.get("deposit_balance_usd", 0)
                db.add(Alert(case_id=case.id, type="freeze_window", severity="high",
                             message=f"Freeze window open: ${bal:,.0f} still at {d.vasp_name} deposit address "
                                     f"{short(d.address)}. Send a freeze request now.",
                             data={"address": d.address, "vasp": d.vasp_name, "balance_usd": bal}))
        before = prev.get((d.vasp_name, d.role))
        if before is not None and (d.confidence - before) * 100 >= rules["score_increase_points"]:
            db.add(Alert(case_id=case.id, type="score_increase", severity="medium",
                         message=f"{d.vasp_name} confidence rose {before:.2f} -> {d.confidence:.2f} since the last trace",
                         data={"vasp": d.vasp_name, "before": before, "after": d.confidence}))
    for n in res.nodes.values():
        if "holds_funds" in n.flags and n.depth > 0 and n.value_share >= 0.05:
            db.add(WatchItem(case_id=case.id, chain=n.chain, address=n.address, reason="private_endpoint", active=active))
        if "sanctioned" in n.flags:
            cats = n.stats.get("risk_categories", [])
            what = ", ".join(c["label"] for c in cats)
            db.add(Alert(case_id=case.id, type="high_risk_wallet" if cats else "sanctioned_hit", severity="high",
                         message=f"Trail touches OFAC-sanctioned {n.stats.get('sanction_entity') or 'address'} "
                                 f"{short(n.address)} on {n.chain}" + (f": {what}" if what else ""),
                         data={"address": n.address, "chain": n.chain, "categories": [c["code"] for c in cats],
                               "entity": n.stats.get("sanction_entity")}))
    for h in res.crosschain:
        db.add(Alert(case_id=case.id, type="cross_chain", severity="medium",
                     message=f"Funds bridged {h['from_chain']} -> {h['to_chain']} via {h['tool'] or h['provider']}: "
                             f"${h['usd_out']:,.0f} arrived at {short(h['to_address'])} after {h['minutes']:.0f} min "
                             f"(continuity {h['continuity']:.2f}). Trail continued on {h['to_chain']}.",
                     data={k: h[k] for k in ("from_chain", "to_chain", "to_address", "dest_tx", "src_tx", "continuity")}))
    big = [e for e in res.edges.values() if e.direction in ("forward", "bridge")
           and e.amount_usd >= rules["large_transfer_usd"]]
    if big:
        top = sorted(big, key=lambda e: -e.amount_usd)[:3]
        db.add(Alert(case_id=case.id, type="large_transfer", severity="medium",
                     message=f"{len(big)} transfer(s) of ${rules['large_transfer_usd']:,.0f}+ on the trail; largest "
                             f"${top[0].amount_usd:,.0f} {short(top[0].frm)} -> {short(top[0].to)}",
                     data={"edges": [{"from": e.frm, "to": e.to, "usd": round(e.amount_usd, 2)} for e in top]}))
    risk = analysis["risk"]
    if rules["risk_patterns"] and analysis["typologies"] and level_at_least(risk["level"], rules["min_risk_level"]):
        names = ", ".join(sorted({t["name"] for t in analysis["typologies"]}))
        db.add(Alert(case_id=case.id, type="risk_pattern", severity="high" if risk["level"] in ("high", "critical") else "medium",
                     message=f"Risk {risk['level'].upper()} ({risk['overall']}/100). Patterns: {names}",
                     data={"level": risk["level"], "overall": risk["overall"],
                           "typologies": [t["code"] for t in analysis["typologies"]]}))
    if not any(d.role == "off_ramp" for d in drafts):
        db.add(Alert(case_id=case.id, type="no_vasp", severity="medium",
                     message="No VASP reached within trace limits. Funds may sit in private wallets: watch-list armed.",
                     data={}))
