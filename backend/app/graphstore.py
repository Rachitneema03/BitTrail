"""Graph export and the optional Neo4j mirror.

BitTrail computes on an in-memory graph (NetworkX-sized traces, <= 2,000 edges) and stores it in Postgres. For
cross-case graph analytics at scale the same graph can be exported (Cypher for Neo4j, GraphML for Gephi / NetworkX)
or mirrored into Neo4j automatically after every trace when NEO4J_URI is set. Postgres stays the system of record.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Case, TraceEdge, TraceJob, TraceNode

log = logging.getLogger("bittrail.graph")


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


def _q(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def cypher_statements(case: Case, nodes, edges) -> list[tuple[str, dict]]:
    """Parameterised MERGE statements: addresses are shared across cases, so Neo4j shows cross-case overlap."""
    out: list[tuple[str, dict]] = [("MERGE (c:Case {case_no: $case_no}) SET c.fir = $fir, c.state = $state",
                                    {"case_no": case.case_no, "fir": case.fir_no, "state": case.state})]
    for n in nodes:
        out.append(("MERGE (a:Address {id: $id}) SET a.chain = $chain, a.address = $address, a.kind = $kind, "
                    "a.entity = $entity WITH a MATCH (c:Case {case_no: $case_no}) "
                    "MERGE (c)-[r:TRACED]->(a) SET r.depth = $depth, r.value_usd = $value_usd",
                    {"id": f"{n.chain}:{n.address}", "chain": n.chain, "address": n.address, "kind": n.kind,
                     "entity": n.entity, "case_no": case.case_no, "depth": n.depth, "value_usd": float(n.value_usd or 0)}))
    for e in edges:
        out.append(("MATCH (a:Address {id: $src}), (b:Address {id: $dst}) "
                    "MERGE (a)-[t:FUNDS {case_no: $case_no, direction: $direction}]->(b) "
                    "SET t.amount_usd = $usd, t.asset = $asset, t.tx = $tx, t.first_ts = $ts, t.cross_chain = $xc",
                    {"src": f"{e.chain}:{e.from_address}", "dst": f"{e.to_chain or e.chain}:{e.to_address}",
                     "case_no": case.case_no, "direction": e.direction, "usd": float(e.amount_usd or 0), "asset": e.asset,
                     "tx": e.tx_hashes[:20], "ts": e.first_ts.isoformat() if e.first_ts else None,
                     "xc": bool(e.to_chain and e.to_chain != e.chain)}))
    return out


def cypher_script(case: Case, nodes, edges) -> str:
    """The same statements as a standalone .cypher file (parameters inlined) for `cypher-shell < file`."""
    lines = [f"// BitTrail case #{case.case_no} (FIR {case.fir_no}) trace graph", "CREATE CONSTRAINT address_id IF NOT "
             "EXISTS FOR (a:Address) REQUIRE a.id IS UNIQUE;"]
    for stmt, params in cypher_statements(case, nodes, edges):
        for k in sorted(params, key=len, reverse=True):
            stmt = stmt.replace(f"${k}", _q(params[k]))
        lines.append(stmt + ";")
    return "\n".join(lines) + "\n"


def _sync(case: Case, nodes, edges) -> int:
    from neo4j import GraphDatabase  # optional dependency, only needed when NEO4J_URI is set

    s = settings()
    stmts = cypher_statements(case, nodes, edges)
    with GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password)) as drv, drv.session() as sess:
        sess.run("CREATE CONSTRAINT address_id IF NOT EXISTS FOR (a:Address) REQUIRE a.id IS UNIQUE")
        for stmt, params in stmts:
            sess.run(stmt, **params)
    return len(stmts)


async def mirror(case: Case, nodes, edges) -> str | None:
    """Mirror a finished trace into Neo4j (best effort: a Neo4j outage never fails a trace)."""
    if not settings().neo4j_uri:
        return None
    try:
        n = await asyncio.to_thread(_sync, case, nodes, edges)
        return f"mirrored to Neo4j ({n} statements)"
    except Exception as e:  # noqa: BLE001
        log.warning("neo4j mirror failed: %s", e)
        return f"Neo4j mirror failed: {e}"
