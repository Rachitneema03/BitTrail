"""Graph export: a finished trace as a NetworkX graph, written out as GraphML (opens in Gephi, yEd, NetworkX).

BitTrail computes on an in-memory graph (traces are small and bounded, <= 2,000 edges) and stores it in Postgres;
no separate graph database is used.
"""
from __future__ import annotations

import io

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Case, TraceEdge, TraceJob, TraceNode


def load(db: Session, job: TraceJob) -> tuple[list[TraceNode], list[TraceEdge]]:
    nodes = db.execute(select(TraceNode).where(TraceNode.job_id == job.id)).scalars().all()
    edges = db.execute(select(TraceEdge).where(TraceEdge.job_id == job.id)).scalars().all()
    return list(nodes), list(edges)


def to_networkx(case: Case, nodes: list[TraceNode], edges: list[TraceEdge]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph(case_no=case.case_no, fir=case.fir_no)
    for n in nodes:
        g.add_node(f"{n.chain}:{n.address}", chain=n.chain, address=n.address, kind=n.kind, entity=n.entity or "",
                   depth=n.depth, value_usd=float(n.value_usd or 0), label_source=n.label_source or "")
    for e in edges:
        g.add_edge(f"{e.chain}:{e.from_address}", f"{e.to_chain or e.chain}:{e.to_address}", direction=e.direction,
                   asset=e.asset, amount_usd=float(e.amount_usd or 0), tx_count=e.tx_count,
                   tx_hashes=",".join(e.tx_hashes[:20]), first_ts=e.first_ts.isoformat() if e.first_ts else "",
                   cross_chain=bool(e.to_chain and e.to_chain != e.chain))
    return g


def graphml(case: Case, nodes, edges) -> str:
    buf = io.BytesIO()
    nx.write_graphml(to_networkx(case, nodes, edges), buf)
    return buf.getvalue().decode("utf-8")
