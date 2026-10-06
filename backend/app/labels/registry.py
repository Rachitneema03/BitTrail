"""VASP registry helpers: actionability of a VASP for Indian law enforcement."""
from __future__ import annotations

from ..config import heuristics
from ..models import Vasp


def actionability(v: Vasp | None) -> tuple[float, str]:
    a = heuristics()["actionability"]
    if v is None:
        return a["unknown"], "Not in VASP registry: route unknown"
    if v.fiu_ind_registered and v.on_sahyog:
        return a["fiu_and_sahyog"], "FIU-IND registered and onboarded on Sahyog"
    if v.fiu_ind_registered:
        return a["fiu_only"], "FIU-IND registered reporting entity: Section 94 BNSS notice applies"
    if v.on_sahyog:
        return a["sahyog_only"], "Onboarded on Sahyog"
    if v.le_portal_url:
        return a["foreign_le_portal"], "Foreign VASP with law-enforcement request portal"
    return a["unknown"], "Registration and Sahyog status unknown: verify route"


def sources(v: Vasp | None) -> list[dict]:
    """'FIU-IND: url | Sahyog: url | LE channel: url' (registry status_source) -> [{label, url}]."""
    out = []
    for part in ((v.status_source if v else "") or "").split(" | "):
        label, sep, url = part.partition(": ")
        if sep and url.startswith("http"):
            out.append({"label": label, "url": url})
    return out


def route(v: Vasp | None, name: str) -> dict:
    """Which channel a request to this VASP should go through, why, and the cited sources (shown with every request)."""
    src = sources(v)
    if v and v.on_sahyog:
        r = {"channel": "sahyog", "label": "Sahyog portal (I4C)", "url": None,
             "why": f"{name} is onboarded on Sahyog" + (" and FIU-IND registered" if v.fiu_ind_registered else "")}
    elif v and v.fiu_ind_registered:
        r = {"channel": "sahyog_notice", "label": "Sahyog / Section 94 notice to the nodal officer", "url": None,
             "why": f"{name} is an FIU-IND registered reporting entity in India: send the notice to its designated "
                    f"nodal officer through Sahyog"}
    elif v and v.le_portal_url:
        r = {"channel": "le_portal", "label": f"{name} law-enforcement request channel", "url": v.le_portal_url,
             "why": f"{name} is not known to be on Sahyog or FIU-IND registered; it accepts law-enforcement requests "
                    f"through its own channel"}
    else:
        r = {"channel": "international", "label": "MLAT (MHA) / Interpol (CBI)", "url": None,
             "why": f"No Indian registration, Sahyog onboarding or law-enforcement channel is on record for {name}: "
                    f"use the international route and verify the VASP's status"}
    if v and v.le_portal_url and r["channel"] != "le_portal":
        r["alt_url"] = v.le_portal_url  # the VASP's own LE channel, for follow-up / preservation requests
    return {**r, "sources": src}
