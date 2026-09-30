"""Seed labels (CSV) and the VASP registry into the database. Idempotent."""
from __future__ import annotations

import csv
import json

from sqlalchemy import func, insert, select

from ..config import BACKEND_DIR
from ..db import SessionLocal
from ..models import Label, Vasp, uid

BATCH = 1000

SEEDS = BACKEND_DIR / "data" / "label_seeds"
REGISTRY = BACKEND_DIR / "data" / "vasp_registry.json"

# Well-known Tornado Cash (Ethereum) contracts -> mixer. Source: public contract registry / Etherscan tags.
TORNADO = [
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",  # router
    "0x12d66f87a04a9e220743712ce6d9bb1b5616b8fc",  # 0.1 ETH
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936",  # 1 ETH
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",  # 10 ETH
    "0xa160cdab225685da1d56aa342ad8841c3b53f291",  # 100 ETH
]


# Well-known bridge / cross-chain router contracts (public explorer name tags). Curated: verify before operational use.
BRIDGES = [
    ("0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae", "LI.FI Diamond", ("ethereum", "polygon", "bsc")),
    ("0x3ee18b2214aff97000d974cf647e7c347e8fa585", "Wormhole Token Bridge", ("ethereum",)),
    ("0xa0c68c638235ee32657e8f720a23cec1bfc77c77", "Polygon PoS Bridge (RootChainManager)", ("ethereum",)),
    ("0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5", "Across SpokePool", ("ethereum",)),
    ("0x8731d54e9d02c286767d56ac03e8037c07e01e98", "Stargate Router", ("ethereum",)),
]


def _vasp_ids(db) -> dict[str, str]:
    return {v.name.lower(): v.id for v in db.execute(select(Vasp)).scalars()}


def seed_registry(db) -> None:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    existing = {v.name.lower(): v for v in db.execute(select(Vasp)).scalars()}
    for r in data["vasps"]:
        v = existing.get(r["name"].lower())
        if v is None:
            v = Vasp(name=r["name"])
            db.add(v)
        for k in ("kind", "country", "fiu_ind_registered", "on_sahyog", "le_portal_url", "nodal_contact", "status_source"):
            if k in r:
                setattr(v, k, r[k])
        if not v.nodal_contact:
            v.nodal_contact = f"Nodal Officer, {r['name']} (placeholder)"
    db.commit()


def seed_labels(db) -> int:
    rows: list[dict] = []
    for f in sorted(SEEDS.glob("*.csv")):
        with open(f, encoding="utf-8") as fh:
            rows.extend(csv.DictReader(fh))
    for addr in TORNADO:
        for chain in ("ethereum",):
            rows.append({"chain": chain, "address": addr, "type": "mixer", "entity_name": "Tornado Cash",
                         "tier": "curated", "source": "curated_mixers", "source_ref": "Tornado Cash contract"})
    for addr, name, chains in BRIDGES:
        for chain in chains:
            rows.append({"chain": chain, "address": addr, "type": "bridge", "entity_name": name,
                         "tier": "curated", "source": "curated_bridges", "source_ref": "public explorer name tag"})
    unique: dict[tuple, dict] = {}
    for r in rows:
        unique.setdefault((r["chain"], r["address"], r["type"], r["source"]), r)
    seeded = db.execute(select(func.count(Label.id)).where(Label.source != "vasp_confirmation")).scalar() or 0
    if seeded >= len(unique):
        return 0

    # make sure every VASP entity exists
    ids = _vasp_ids(db)
    for r in unique.values():
        if r["type"].startswith("vasp") and r["entity_name"].lower() not in ids:
            v = Vasp(name=r["entity_name"], kind="exchange", nodal_contact=f"Nodal Officer, {r['entity_name']} (placeholder)",
                     status_source="Unknown")
            db.add(v)
            db.flush()
            ids[v.name.lower()] = v.id
    db.commit()

    # resume-safe: skip keys already present, insert the rest in committed batches (poolers drop huge statements)
    existing = set(db.execute(select(Label.chain, Label.address, Label.type, Label.source)).all()) if seeded else set()
    todo = [r for k, r in unique.items() if k not in existing]
    for i in range(0, len(todo), BATCH):
        db.execute(insert(Label), [
            {"id": uid(), "chain": r["chain"], "address": r["address"], "type": r["type"], "entity_name": r["entity_name"],
             "tier": r["tier"], "source": r["source"], "source_ref": r.get("source_ref"), "negative": False,
             "vasp_id": ids.get(r["entity_name"].lower()) if r["type"].startswith("vasp") else None}
            for r in todo[i:i + BATCH]])
        db.commit()
    return len(todo)


def seed_all() -> None:
    with SessionLocal() as db:
        seed_registry(db)
        seed_labels(db)
