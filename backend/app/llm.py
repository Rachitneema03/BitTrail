"""Sarvam AI integration: narrate evidence, answer questions about a case, translate notices.

Guardrails (CONTEXT.md principle 2): the LLM only ever sees the facts BitTrail already computed, is told to use
nothing else, and its output is labelled AI-written. It never decides, re-ranks or re-scores an attribution.
Without SARVAM_API_KEY: summaries fall back to a deterministic template; Q&A and translation are unavailable.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters.base import AdapterUnavailable
from .adapters.http import cached_get
from .config import settings
from .models import Candidate, Case, CaseLink, CaseWallet, TraceEdge, TraceJob

SYSTEM = (
    "You are BitTrail's evidence narrator for Indian police investigators working on crypto-fraud cases. "
    "Rules: (1) Use ONLY the facts in the JSON provided. Never add addresses, amounts, exchanges, dates, people or "
    "conclusions that are not in it. (2) Never change, re-rank or invent confidence scores or attributions; report "
    "them exactly as given, and say they come from BitTrail's rule-based engine. (3) When you cite a movement, quote "
    "the first 10 characters of its transaction hash. (4) If the facts do not answer something, say it is not "
    "established by the trace. (5) Plain language, short sentences, no markdown tables."
)


class LLMUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(settings().sarvam_api_key)


def status() -> dict:
    s = settings()
    return {"provider": "Sarvam AI", "configured": configured(), "model": s.sarvam_model,
            "translate_model": "sarvam-translate:v1", "used_for_attribution": False}


def _headers() -> dict:
    return {"api-subscription-key": settings().sarvam_api_key, "Content-Type": "application/json"}


async def chat(user: str, max_tokens: int = 1200) -> str:
    s = settings()
    if not configured():
        raise LLMUnavailable("SARVAM_API_KEY not set")
    body = {"model": s.sarvam_model, "temperature": 0.2, "max_tokens": max_tokens, "reasoning_effort": "low",
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    try:
        data = await cached_get("sarvam", f"{s.sarvam_base}/v1/chat/completions", None, _headers(), None, json_body=body)
    except AdapterUnavailable as e:
        raise LLMUnavailable(str(e)) from e
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


async def translate(text: str, target: str = "hi-IN") -> str:
    s = settings()
    if not configured():
        raise LLMUnavailable("SARVAM_API_KEY not set")
    chunks, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > 1800 and cur:
            chunks.append(cur)
            cur = ""
        cur += para + "\n"
    if cur.strip():
        chunks.append(cur)
    out = []
    for c in chunks:
        if not c.strip():
            out.append(c)
            continue
        body = {"input": c.strip(), "source_language_code": "en-IN", "target_language_code": target,
                "model": "sarvam-translate:v1"}
        try:
            data = await cached_get("sarvam", f"{s.sarvam_base}/translate", None, _headers(), None, json_body=body)
        except AdapterUnavailable as e:
            raise LLMUnavailable(str(e)) from e
        out.append(data.get("translated_text", ""))
    return "\n".join(out).strip()


def case_facts(db: Session, case: Case) -> dict:
    """The only material the LLM may use: what BitTrail already computed for the latest completed trace."""
    job = db.execute(select(TraceJob).where(TraceJob.case_id == case.id, TraceJob.status == "done")
                     .order_by(TraceJob.created_at.desc()).limit(1)).scalar()
    wallets = db.execute(select(CaseWallet).where(CaseWallet.case_id == case.id)).scalars().all()
    facts: dict = {"case": {"case_no": case.case_no, "fir": case.fir_no, "state": case.state, "fraud_type": case.fraud_type,
                            "reported": case.fraud_time.isoformat(), "amount_inr": case.amount_inr,
                            "suspect_wallets": [f"{w.chain}:{w.address}" for w in wallets]}}
    if not job:
        facts["trace"] = "no completed trace yet"
        return facts
    cands = db.execute(select(Candidate).where(Candidate.job_id == job.id)
                       .order_by(Candidate.role, Candidate.rank_score.desc())).scalars().all()
    edges = db.execute(select(TraceEdge).where(TraceEdge.job_id == job.id)
                       .order_by(TraceEdge.amount_usd.desc()).limit(12)).scalars().all()
    links = db.execute(select(CaseLink).where((CaseLink.case_a == case.id) | (CaseLink.case_b == case.id))).scalars().all()
    a = job.analysis or {}
    facts["trace"] = {"addresses": (job.progress or {}).get("nodes"), "links": (job.progress or {}).get("edges"),
                      "usd_followed": (job.progress or {}).get("seed_out_usd"), "finished": job.finished_at.isoformat() if job.finished_at else None}
    facts["candidates"] = [{"vasp": c.vasp_name, "role": c.role, "address": c.address, "kind": c.address_kind, "hops": c.hops,
                            "value_share": c.value_share, "confidence": c.confidence, "actionability": c.actionability,
                            "funds_status": c.funds_status, "reasons": c.reasons[:5],
                            "score_breakdown": (c.explain or {}).get("contributions"),
                            "evidence_tx": c.evidence_tx[:3]} for c in cands[:5]]
    facts["largest_movements"] = [{"from": e.from_address, "to": e.to_address, "usd": e.amount_usd, "asset": e.asset,
                                   "type": e.direction, "first_seen": e.first_ts.isoformat() if e.first_ts else None,
                                   "tx": e.tx_hashes[:1]} for e in edges]
    facts["risk"] = a.get("risk")
    facts["typologies"] = [{"name": t["name"], "detail": t["detail"]} for t in a.get("typologies", [])]
    facts["cross_case_links"] = [{"address": l.address, "kind": l.kind, "entity": l.entity} for l in links]
    return facts


def template_narrative(f: dict) -> str:
    """Deterministic summary used when Sarvam AI is not configured."""
    c = f["case"]
    lines = [f"Case #{c['case_no']} (FIR {c['fir']}, {c.get('state') or 'state n/a'}): {c.get('fraud_type') or 'cyber fraud'} "
             f"reported {c['reported'][:10]}. Suspect wallet(s): {', '.join(c['suspect_wallets'])}."]
    if isinstance(f.get("trace"), str):
        return lines[0] + " No completed trace yet."
    t = f["trace"]
    lines.append(f"BitTrail traced {t['addresses']} addresses and {t['links']} links, following ${t['usd_followed'] or 0:,.0f} of outflow.")
    off = [x for x in f["candidates"] if x["role"] == "off_ramp"]
    on = [x for x in f["candidates"] if x["role"] == "on_ramp"]
    if off:
        top = off[0]
        lines.append(f"The nearest exchange is {top['vasp']}: {top['value_share']:.0%} of the traced value reached its "
                     f"{top['kind'].replace('_', ' ')} {top['address']} in {top['hops']} hop(s), confidence {top['confidence']:.2f} "
                     f"(rule-based), funds {top['funds_status'].replace('_', ' ')}.")
        if top.get("reasons"):
            lines.append("Main evidence: " + top["reasons"][0] + ".")
    else:
        lines.append("No exchange was reached within the trace limits.")
    if on:
        lines.append(f"The suspect wallet was funded from {on[0]['vasp']} ({on[0]['value_share']:.0%} of its prior inflow).")
    if f.get("risk"):
        lines.append(f"Risk is {f['risk']['level'].upper()} ({f['risk']['overall']}/100)"
                     + (f"; patterns detected: {', '.join(t['name'] for t in f['typologies'])}." if f["typologies"] else "."))
    if f.get("cross_case_links"):
        lines.append(f"The trail shares {len(f['cross_case_links'])} address(es) with other cases.")
    return " ".join(lines)


def narrative_prompt(f: dict) -> str:
    return ("Write a 120-180 word investigation summary for the investigating officer, in English, from these BitTrail "
            "facts. Cover: the suspect wallet, where the money went (exchange, deposit address, hops, confidence as given), "
            "where it came from, risk level and patterns, cross-case links, and the recommended next step (send the "
            "Sahyog notice to the top exchange). Facts JSON:\n" + json.dumps(f, default=str))


def ask_prompt(f: dict, question: str) -> str:
    return ("Answer the investigator's question using only these BitTrail facts. If the facts do not contain the answer, "
            "say so. Keep it under 120 words.\nFacts JSON:\n" + json.dumps(f, default=str) + f"\n\nQuestion: {question}")
