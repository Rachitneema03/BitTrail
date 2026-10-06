"""Retrieval for "Ask this case": BM25 over the case's own computed evidence + the reference notes (data/kb.md).

The LLM only ever sees the retrieved passages and must cite them as [n]. Without Sarvam AI the endpoint still answers
with the top passages themselves (extractive), so the feature works offline. Retrieval decides nothing: it only
selects which already-computed facts are shown.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import BACKEND_DIR
from .models import Alert, Candidate, Case, CaseLink, CaseWallet, Request, TraceEdge, TraceJob, TraceNode

KB = BACKEND_DIR / "data" / "kb.md"
TOKEN = re.compile(r"[A-Za-z0-9]+")
STOP = set("the a an of to in on and or is are was were be by for with at from this that it as which what why how "
           "who whom does did do can could should would will not no".split())


def _short(a: str | None) -> str:
    return f"{a[:8]}…{a[-4:]}" if a and len(a) > 14 else (a or "")


def tokens(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text):
        lt = t.lower()
        if lt in STOP or len(lt) < 2:
            continue
        out.append(lt)
        if len(lt) >= 12:  # addresses / hashes: also index a prefix so "TADSuFLf" finds the full address
            out.append(lt[:8])
    return out


@lru_cache
def kb_chunks() -> list[dict]:
    text = KB.read_text(encoding="utf-8") if KB.exists() else ""
    out = []
    for part in text.split("\n## ")[1:]:
        title, _, body = part.partition("\n")
        out.append({"id": f"kb:{title.strip()[:40]}", "kind": "reference", "title": title.strip(),
                    "text": " ".join(body.split())})
    return out


def case_chunks(db: Session, case: Case) -> list[dict]:
    """Every computed fact about the case, as small retrievable passages."""
    ch: list[dict] = []
    add = lambda cid, kind, title, text, ref=None: ch.append({"id": cid, "kind": kind, "title": title, "text": text, "ref": ref})  # noqa: E731
    wallets = db.execute(select(CaseWallet).where(CaseWallet.case_id == case.id)).scalars().all()
    add("case", "case", f"Case #{case.case_no}",
        f"FIR {case.fir_no}, NCRP {case.ncrp_id or '-'}, {case.police_station or ''} {case.state or ''}. "
        f"{case.fraud_type or 'Cyber fraud'} reported {case.fraud_time:%d %b %Y}"
        + (f", loss ₹{case.amount_inr:,.0f}" if case.amount_inr else "") + ". Suspect wallets: "
        + ", ".join(f"{w.address} ({w.chain})" for w in wallets) + ".")
    job = db.execute(select(TraceJob).where(TraceJob.case_id == case.id, TraceJob.status == "done")
                     .order_by(TraceJob.created_at.desc()).limit(1)).scalar()
    if job:
        p, a = job.progress or {}, job.analysis or {}
        add("trace", "trace", "Trace summary",
            f"Traced {p.get('nodes')} addresses and {p.get('edges')} links across chains {', '.join(a.get('chains') or [])}, "
            f"following ${p.get('seed_out_usd') or 0:,.0f} of outflow in {p.get('seconds')} s. "
            f"{p.get('bridges') or 0} cross-chain hop(s). Notes: {'; '.join((p.get('notes') or [])[:4])}")
        for c in db.execute(select(Candidate).where(Candidate.job_id == job.id).order_by(Candidate.rank_score.desc())).scalars():
            contrib = ", ".join(f"{x['label']} {x['points']:.0f} pts" for x in (c.explain or {}).get("contributions", []))
            add(f"cand:{c.id}", "candidate", f"{c.vasp_name} ({c.role.replace('_', '-')})",
                f"{c.vasp_name} {c.role.replace('_', '-')} candidate: {c.address_kind.replace('_', ' ')} {c.address} on {c.chain}, "
                f"{c.hops} hops, {c.value_share:.0%} of traced value (${c.value_usd:,.0f}), confidence {c.confidence:.2f}, "
                f"actionability {c.actionability:.2f}, rank {c.rank_score:.3f}, funds {c.funds_status.replace('_', ' ')}. "
                f"Score breakdown: {contrib}. Reasons: {' | '.join(c.reasons)}. Evidence tx: {', '.join(c.evidence_tx[:4])}",
                {"chain": c.chain, "address": c.address})
        for n in db.execute(select(TraceNode).where(TraceNode.job_id == job.id)).scalars():
            if n.kind == "intermediary" and not n.reasons:
                continue
            add(f"node:{n.chain}:{n.address}", "address", f"{n.entity + ' ' if n.entity else ''}{n.kind.replace('_', ' ')} {_short(n.address)}",
                f"{n.kind.replace('_', ' ')} address {n.address} on {n.chain}, depth {n.depth}, "
                f"{n.value_share:.1%} of traced value (${n.value_usd:,.0f})" + (f", entity {n.entity}" if n.entity else "")
                + (f", label {n.label_source} ({n.label_tier})" if n.label_source else "")
                + (f", flags {', '.join(n.flags)}" if n.flags else "") + ". " + " ".join(n.reasons),
                {"chain": n.chain, "address": n.address})
        for e in db.execute(select(TraceEdge).where(TraceEdge.job_id == job.id).order_by(TraceEdge.amount_usd.desc()).limit(80)).scalars():
            dest = e.to_chain or e.chain
            add(f"edge:{e.id}", "transfer", f"{e.direction} {_short(e.from_address)} → {_short(e.to_address)}",
                f"{e.direction} transfer of ${e.amount_usd:,.0f} {e.asset} from {e.from_address} ({e.chain}) to {e.to_address} ({dest}) "
                + (f"first seen {e.first_ts:%d %b %Y %H:%M} UTC, " if e.first_ts else "")
                + f"{e.tx_count} transaction(s): {', '.join(e.tx_hashes[:3])}",
                {"chain": e.chain, "tx": e.tx_hashes[:1]})
        for h in a.get("crosschain") or []:
            add(f"xchain:{h['src_tx']}", "cross-chain", f"{h['from_chain']} → {h['to_chain']} via {h['tool']}",
                f"Cross-chain hop {h['from_chain']} to {h['to_chain']} via {h['tool']} (tracker {h['provider']}): "
                f"${h['usd_in']:,.0f} in through {h['bridge_address']} (tx {h['src_tx']}), ${h['usd_out']:,.0f} out to "
                f"{h['to_address']} (tx {h['dest_tx']}) after {h['minutes']} minutes. Continuity {h['continuity']} "
                f"(amount {h['components']['amount']}, time {h['components']['time']}, tracker-confirmed {h['confirmed']}).")
        risk = a.get("risk") or {}
        if risk:
            add("risk", "risk", "Risk profile",
                f"Overall risk {risk.get('level')} {risk.get('overall')}/100. "
                + " ".join(f"{x['label']} {x['score']}: {x['why']}." for x in risk.get("axes", []))
                + "".join(f" High-risk category: {c['label']} ({', '.join(c.get('entities', []))})." for c in risk.get("categories", [])))
        for i, t in enumerate(a.get("typologies") or []):
            add(f"typ:{i}", "pattern", t["name"], f"Laundering pattern {t['name']} ({t['severity']}): {t['detail']}. "
                f"Addresses {', '.join(t['addresses'][:4])}. Tx {', '.join(t['tx'][:3])}")
    for l in db.execute(select(CaseLink).where((CaseLink.case_a == case.id) | (CaseLink.case_b == case.id))).scalars():
        peer = db.get(Case, l.case_b if l.case_a == case.id else l.case_a)
        add(f"link:{l.id}", "case link", f"Linked to case #{peer.case_no}",
            f"Shares {l.kind.replace('_', ' ')} {l.address} ({l.entity or 'no entity'}) with case #{peer.case_no} "
            f"(FIR {peer.fir_no}, {peer.state}). Likely the same beneficiary: consolidate the request.")
    for r in db.execute(select(Request).where(Request.case_id == case.id)).scalars():
        add(f"req:{r.id}", "request", f"Request to {r.vasp_name}",
            f"{r.legal_basis} request ({r.type.replace('_', ' ')}) to {r.vasp_name}, status {r.status}"
            + (f", Sahyog ref {r.sahyog_ref}" if r.sahyog_ref else "") + f", addresses {', '.join(r.addresses)}.")
    for al in db.execute(select(Alert).where(Alert.case_id == case.id)).scalars():
        add(f"alert:{al.id}", "alert", al.type.replace("_", " "), f"Alert ({al.severity}) {al.created_at:%d %b %Y}: {al.message}")
    return ch


def bm25(chunks: list[dict], query: str, k: int = 6, k1: float = 1.4, b: float = 0.75) -> list[tuple[float, dict]]:
    q = tokens(query)
    if not q or not chunks:
        return []
    docs = [tokens(c["title"] + " " + c["text"]) for c in chunks]
    avg = sum(len(d) for d in docs) / len(docs)
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    scored = []
    for c, d in zip(chunks, docs):
        tf = Counter(d)
        s = 0.0
        for t in set(q):
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        if c["kind"] == "reference":
            s *= 0.8  # prefer the case's own evidence over general notes
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return scored[:k]


def retrieve(db: Session, case: Case, question: str, k: int = 6) -> list[dict]:
    hits = bm25(case_chunks(db, case) + kb_chunks(), question, k)
    return [{**c, "n": i + 1, "score": round(s, 2)} for i, (s, c) in enumerate(hits)]


def rag_prompt(question: str, passages: list[dict]) -> str:
    ctx = "\n".join(f"[{p['n']}] ({p['kind']}) {p['title']}: {p['text']}" for p in passages)
    return ("Answer the investigator's question using ONLY the numbered passages below, which BitTrail retrieved from "
            "this case's computed evidence and its reference notes. Cite passages like [1] after each claim. If the "
            "passages do not contain the answer, say that the trace does not establish it. Never change scores or "
            f"attributions. Under 150 words.\n\nPassages:\n{ctx}\n\nQuestion: {question}")


def extractive_answer(passages: list[dict]) -> str:
    if not passages:
        return "Nothing in this case's evidence or the reference notes matches the question."
    lines = ["Most relevant evidence (retrieved, no LLM):"]
    for p in passages[:4]:
        first = re.split(r"(?<=[.!?])\s", p["text"], maxsplit=2)
        lines.append(f"[{p['n']}] {p['title']}: {' '.join(first[:2])[:320]}")
    return "\n".join(lines)
