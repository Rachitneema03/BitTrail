"""Cross-case correlation on shared deposit / intermediary addresses (docs/architecture.md §4.5)."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .engine.classify import short
from .engine.model import TraceResult
from .models import Alert, AddressCaseIndex, Case, CaseLink

# Hot wallets and services are shared by millions of users: never link on them.
LINKABLE = {"suspect", "intermediary", "vasp_deposit", "offramp", "sanctioned"}


def update_links(db: Session, case: Case, job_id: str, res: TraceResult) -> list[CaseLink]:
    db.execute(delete(AddressCaseIndex).where(AddressCaseIndex.case_id == case.id))
    rows = []
    for n in res.nodes.values():
        if n.kind in LINKABLE and n.depth >= 0 and (n.kind != "intermediary" or n.value_share >= 0.05):
            rows.append(AddressCaseIndex(chain=n.chain, address=n.address, case_id=case.id, kind=n.kind,
                                         value_share=n.value_share, job_id=job_id))
    db.add_all(rows)
    db.flush()

    links: list[CaseLink] = []
    new_by_peer: dict[str, list[CaseLink]] = {}
    for r in rows:
        others = db.execute(select(AddressCaseIndex).where(
            AddressCaseIndex.chain == r.chain, AddressCaseIndex.address == r.address,
            AddressCaseIndex.case_id != case.id)).scalars().all()
        for o in others:
            a, b = sorted([case.id, o.case_id])
            exists = db.execute(select(CaseLink).where(CaseLink.case_a == a, CaseLink.case_b == b,
                                                       CaseLink.chain == r.chain, CaseLink.address == r.address)).scalar()
            if exists:
                continue
            node = res.nodes.get(f"{r.chain}:{r.address}")
            link = CaseLink(case_a=a, case_b=b, chain=r.chain, address=r.address, kind=r.kind,
                            entity=node.entity if node else None)
            db.add(link)
            links.append(link)
            new_by_peer.setdefault(o.case_id, []).append(link)

    # one alert per linked case pair, listing every shared address
    for peer_id, ls in new_by_peer.items():
        other = db.get(Case, peer_id)
        shared = ", ".join(describe(l) for l in sorted(ls, key=lambda l: l.kind != "vasp_deposit"))
        for c, peer in ((case, other), (other, case)):
            db.add(Alert(case_id=c.id, type="case_link", severity="high",
                         message=f"Linked to Case #{peer.case_no} ({peer.state or 'n/a'}): both trails share {shared}. "
                                 f"Likely the same beneficiary: consider one consolidated request.",
                         data={"peer_case_id": peer.id, "peer_case_no": peer.case_no,
                               "addresses": [{"chain": l.chain, "address": l.address, "kind": l.kind, "entity": l.entity} for l in ls]}))
    return links


def describe(l: CaseLink) -> str:
    if l.kind == "vasp_deposit":
        return f"{l.entity or 'VASP'} deposit address {short(l.address)}"
    return f"{l.kind.replace('_', ' ')} wallet {short(l.address)}"
