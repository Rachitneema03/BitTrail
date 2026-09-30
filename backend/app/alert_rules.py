"""Configurable alert rules (stored in the `settings` table, defaults from heuristics.yaml)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .config import heuristics
from .models import Setting

KEY = "alert_rules"
LEVELS = ["low", "medium", "high", "critical"]


def get_rules(db: Session) -> dict:
    row = db.get(Setting, KEY)
    return {**heuristics()["alerts_default"], **(row.value if row else {})}


def save_rules(db: Session, value: dict) -> dict:
    allowed = set(heuristics()["alerts_default"])
    clean = {k: v for k, v in value.items() if k in allowed}
    if "min_risk_level" in clean and clean["min_risk_level"] not in LEVELS:
        clean.pop("min_risk_level")
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=clean))
    else:
        row.value = {**row.value, **clean}
    return {**heuristics()["alerts_default"], **(row.value if row else clean)}


def level_at_least(level: str, minimum: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(minimum)
