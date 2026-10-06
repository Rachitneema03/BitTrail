"""Run a trace from the command line (no API server needed).

  python scripts/trace_cli.py tron T... --since 2026-01-01T00:00:00Z [--depth 5]
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.adapters import bridges, get_adapter  # noqa: E402
from app.config import heuristics  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.engine.model import TraceParams  # noqa: E402
from app.engine.score import score  # noqa: E402
from app.engine.trace import trace  # noqa: E402
from app.labels.index import label_index  # noqa: E402
from app.labels.registry import actionability  # noqa: E402
from app.labels.seed import seed_all  # noqa: E402
from app.models import Vasp  # noqa: E402


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("chain")
    p.add_argument("address")
    p.add_argument("--since", required=True)
    p.add_argument("--depth", type=int, default=5)
    a = p.parse_args()
    init_db()
    seed_all()
    with SessionLocal() as db:
        vasps = {v.name: v for v in db.execute(select(Vasp)).scalars()}
    since = datetime.fromisoformat(a.since.replace("Z", "+00:00"))
    cfg = heuristics()

    async def fallback(chain, sender, t):
        return await bridges.same_address_match(chain, sender, t, get_adapter, cfg)

    t0 = time.monotonic()
    res = await trace([(a.chain, a.address)], since, TraceParams(max_depth=a.depth), label_index(),
                      get_adapter, cfg, bridge_resolver=bridges.resolve, fallback=fallback)
    print(f"nodes={len(res.nodes)} edges={len(res.edges)} seed_out_usd={res.seed_out_usd:,.0f} "
          f"seconds={time.monotonic() - t0:.1f} dust={res.dust}")
    for n in sorted(res.nodes.values(), key=lambda n: n.depth):
        print(f"  d={n.depth:>2} {n.chain:<9} {n.kind:<16} {n.value_share:6.3f} {n.entity or '':<14} {n.address}")
    for h in res.crosschain:
        print(f"  CROSS-CHAIN {h['from_chain']}->{h['to_chain']} via {h['tool']} ({h['provider']}) "
              f"${h['usd_in']:,.0f}->${h['usd_out']:,.0f} {h['minutes']}min continuity={h['continuity']}")
    for d in score(res, since, heuristics(), lambda e: actionability(vasps.get(e))):
        print(f"\n[{d.role}] {d.vasp_name} {d.address} hops={d.hops} share={d.value_share:.2f} "
              f"conf={d.confidence:.2f} act={d.actionability:.2f} rank={d.rank_score:.3f}")
        for r in d.reasons:
            print("   -", r)
    for note in res.notes:
        print("note:", note)


if __name__ == "__main__":
    asyncio.run(main())
