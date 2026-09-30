"""Watch-list poller: alerts when funds on a watched address move (docs/architecture.md §4.7)."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from ..adapters import AdapterUnavailable, get_adapter
from ..alert_rules import get_rules
from ..config import settings
from ..db import SessionLocal
from ..engine.classify import short
from ..labels.index import label_index
from ..models import Alert, WatchItem, now

log = logging.getLogger("bittrail.watch")


async def check_item(item_id: str) -> int:
    with SessionLocal() as db:
        w = db.get(WatchItem, item_id)
        if w is None or not w.active:
            return 0
        chain, address, since, last_tx, case_id, entity = w.chain, w.address, w.last_checked_at, w.last_seen_tx, w.case_id, w.entity
    try:
        outs = await get_adapter(chain).get_transfers(address, "out", since, None)
    except AdapterUnavailable:
        return 0
    new = [t for t in outs if t.tx_hash != last_tx and t.amount_usd >= 1]
    labels = label_index()
    with SessionLocal() as db:
        rules = get_rules(db)
        w = db.get(WatchItem, item_id)
        w.last_checked_at = now()
        for t in new:
            lab = labels.primary(chain, t.to_address)
            to_vasp = lab and lab.type.startswith("vasp")
            large = t.amount_usd >= rules["large_transfer_usd"]
            if not (rules["new_activity"] or to_vasp or large):
                continue
            where = f"{lab.entity} ({lab.type.replace('_', ' ')})" if lab else short(t.to_address)
            what = {"deposit_hold": f"{entity} deposit" if entity else "deposit", "suspect_wallet": "suspect wallet",
                    "private_endpoint": "end-point wallet"}.get(w.reason, "watched address")
            db.add(Alert(case_id=case_id, watch_item_id=w.id,
                         type="reached_vasp" if to_vasp else "large_transfer" if large else "funds_moved",
                         severity="high" if to_vasp or large or w.reason == "deposit_hold" else "medium",
                         message=f"New activity: ${t.amount_usd:,.0f} {t.asset} left {what} {short(address)} → {where}",
                         data={"tx_hash": t.tx_hash, "to": t.to_address, "amount_usd": t.amount_usd,
                               "timestamp": t.timestamp.isoformat()}))
            w.last_seen_tx = t.tx_hash
        db.commit()
    return len(new)


async def poll_forever() -> None:
    s = settings()
    while True:
        await asyncio.sleep(s.watch_interval_seconds)
        if s.demo_mode:
            continue
        try:
            with SessionLocal() as db:
                ids = [w.id for w in db.execute(select(WatchItem).where(WatchItem.active.is_(True))).scalars()]
            for i in ids:
                await check_item(i)
        except Exception:  # noqa: BLE001
            log.exception("watch poll failed")
