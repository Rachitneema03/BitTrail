"""Append-only, hash-chained audit log."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, now

GENESIS = "0" * 64


def audit(db: Session, action: str, entity: str, entity_id: str | None, user_id: str | None = None, data: dict | None = None) -> None:
    last = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar()
    prev = last or GENESIS
    at = now()
    payload = json.dumps(
        {"at": at.isoformat(), "user": user_id, "action": action, "entity": entity, "id": entity_id, "data": data or {}},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    h = hashlib.sha256((prev + payload).encode()).hexdigest()
    db.add(AuditLog(at=at, user_id=user_id, action=action, entity=entity, entity_id=entity_id, data=data or {}, prev_hash=prev, hash=h))
