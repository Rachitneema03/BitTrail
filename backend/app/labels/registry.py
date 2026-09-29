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
