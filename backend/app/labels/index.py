"""In-memory label index used by the classifier (rebuilt when labels change)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Label

TIER_ORDER = {"verified": 0, "published": 1, "curated": 2, "community": 3, "inferred": 4}
TYPE_ORDER = {"mixer": 0, "bridge": 1, "vasp_deposit": 2, "vasp_hot": 3, "vasp_cold": 4, "offramp": 5,
              "scam": 6, "sanctioned": 7}
VASP_TYPES = {"vasp_hot", "vasp_cold", "vasp_deposit"}


@dataclass(frozen=True)
class LabelRec:
    type: str
    entity: str
    tier: str
    source: str
    negative: bool = False


class LabelIndex:
    def __init__(self, rows: dict[tuple[str, str], list[LabelRec]] | None = None):
        self._rows = rows or {}

    @classmethod
    def from_db(cls) -> "LabelIndex":
        rows: dict[tuple[str, str], list[LabelRec]] = {}
        with SessionLocal() as db:
            for l in db.execute(select(Label)).scalars():
                rows.setdefault((l.chain, l.address), []).append(
                    LabelRec(l.type, l.entity_name, l.tier, l.source, l.negative))
        return cls(rows)

    def all(self, chain: str, address: str) -> list[LabelRec]:
        return self._rows.get((chain, address), [])

    def primary(self, chain: str, address: str) -> LabelRec | None:
        """Most decisive positive label (type priority, then tier). Negative labels veto same entity+type."""
        recs = self.all(chain, address)
        vetoed = {(r.entity, r.type) for r in recs if r.negative}
        pos = [r for r in recs if not r.negative and (r.entity, r.type) not in vetoed and r.type != "sanctioned"]
        if not pos:
            return None
        return sorted(pos, key=lambda r: (TYPE_ORDER.get(r.type, 9), TIER_ORDER.get(r.tier, 9)))[0]

    def sanctioned(self, chain: str, address: str) -> LabelRec | None:
        return next((r for r in self.all(chain, address) if r.type == "sanctioned" and not r.negative), None)

    def __len__(self) -> int:
        return len(self._rows)


_index: LabelIndex | None = None


def label_index() -> LabelIndex:
    global _index
    if _index is None:
        _index = LabelIndex.from_db()
    return _index


def invalidate() -> None:
    global _index
    _index = None
