"""Timeline, monitoring, alert rules and Sarvam AI endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import llm
from ..alert_rules import get_rules, save_rules
from ..audit import audit
from ..auth import require
from ..db import get_db
from ..models import Case, Request, TraceJob, User, WatchItem
from ..timeline import build_timeline

router = APIRouter(prefix="/api/v1", tags=["insights"])


class MonitorIn(BaseModel):
    active: bool


class NarrativeIn(BaseModel):
    lang: str = "en-IN"


class AskIn(BaseModel):
    question: str


class TranslateIn(BaseModel):
    lang: str = "hi-IN"


def _case(db: Session, case_id: str) -> Case:
    c = db.get(Case, case_id)
    if not c:
        raise HTTPException(404, "Case not found")
    return c


@router.get("/cases/{case_id}/timeline")
def timeline(case_id: str, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    return build_timeline(db, _case(db, case_id))


@router.post("/cases/{case_id}/monitor")
def monitor(case_id: str, data: MonitorIn, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    c = _case(db, case_id)
    c.monitoring = data.active
    for w in db.execute(select(WatchItem).where(WatchItem.case_id == case_id)).scalars():
        w.active = data.active
    audit(db, "case.monitor", "case", case_id, user.id, {"active": data.active})
    db.commit()
    return {"monitoring": data.active}


@router.get("/settings/alerts")
def alert_rules(db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    return get_rules(db)


@router.put("/settings/alerts")
def update_alert_rules(data: dict, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    rules = save_rules(db, data)
    audit(db, "settings.alerts", "setting", None, user.id, data)
    db.commit()
    return rules


@router.get("/ai/status")
def ai_status(user: User = Depends(require("io", "analyst", "vasp"))):
    return llm.status()


@router.post("/cases/{case_id}/narrative")
async def narrative(case_id: str, data: NarrativeIn, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    c = _case(db, case_id)
    facts = llm.case_facts(db, c)
    source, model = "template", None
    if llm.configured():
        try:
            text = await llm.chat(llm.narrative_prompt(facts))
            source, model = "sarvam", llm.status()["model"]
            if data.lang != "en-IN":
                text = await llm.translate(text, data.lang)
        except llm.LLMUnavailable as e:
            text = llm.template_narrative(facts) + f"\n\n(Sarvam AI unavailable: {e}; template summary shown.)"
    else:
        text = llm.template_narrative(facts)
    job = db.execute(select(TraceJob).where(TraceJob.case_id == case_id, TraceJob.status == "done")
                     .order_by(TraceJob.created_at.desc()).limit(1)).scalar()
    if job:
        a = dict(job.analysis or {})
        a["narratives"] = {**a.get("narratives", {}), data.lang: {"text": text, "source": source, "model": model}}
        job.analysis = a
    audit(db, "ai.narrative", "case", case_id, user.id, {"lang": data.lang, "source": source, "model": model})
    db.commit()
    return {"text": text, "source": source, "model": model, "lang": data.lang}


@router.post("/cases/{case_id}/ask")
async def ask(case_id: str, data: AskIn, db: Session = Depends(get_db), user: User = Depends(require("io", "analyst"))):
    c = _case(db, case_id)
    q = data.question.strip()[:500]
    if not q:
        raise HTTPException(422, "Empty question")
    if not llm.configured():
        raise HTTPException(503, "Sarvam AI is not configured (set SARVAM_API_KEY). All evidence is still on this page.")
    try:
        answer = await llm.chat(llm.ask_prompt(llm.case_facts(db, c), q), max_tokens=800)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, f"Sarvam AI unavailable: {e}")
    audit(db, "ai.ask", "case", case_id, user.id, {"question": q})
    db.commit()
    return {"answer": answer, "model": llm.status()["model"],
            "note": "AI-written from BitTrail's evidence; not used for attribution. Verify against the cited transactions."}


@router.post("/requests/{req_id}/translate")
async def translate_request(req_id: str, data: TranslateIn, db: Session = Depends(get_db),
                            user: User = Depends(require("io", "analyst", "vasp"))):
    r = db.get(Request, req_id)
    if not r:
        raise HTTPException(404, "Request not found")
    if not llm.configured():
        raise HTTPException(503, "Sarvam AI is not configured (set SARVAM_API_KEY)")
    try:
        text = await llm.translate(r.body_md.replace("**", "").replace("`", ""), data.lang)
    except llm.LLMUnavailable as e:
        raise HTTPException(503, f"Sarvam AI unavailable: {e}")
    r.translations = {**(r.translations or {}), data.lang: text}
    audit(db, "ai.translate", "request", req_id, user.id, {"lang": data.lang})
    db.commit()
    return {"lang": data.lang, "text": text}
