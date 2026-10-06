"""Trace-time benchmark on live data: every demo case, cold (empty API cache) then warm, plus a depth sweep.

  DATABASE_URL=sqlite:///fresh.db python scripts/benchmark.py      # use a FRESH database so "cold" is really cold
Writes docs/benchmark.md (tables) and docs/benchmark.json (data for the slide-4 scalability chart).
"""
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters import bridges, detect_chain, get_adapter, normalize_address  # noqa: E402
from app.config import BACKEND_DIR, ROOT_DIR, heuristics, settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.engine.model import TraceParams  # noqa: E402
from app.engine.score import score  # noqa: E402
from app.engine.trace import trace  # noqa: E402
from app.labels.index import label_index  # noqa: E402
from app.labels.seed import seed_all  # noqa: E402


async def run(seeds, since, depth: int = 5) -> dict:
    cfg = heuristics()

    async def fallback(chain, sender, t):
        return await bridges.same_address_match(chain, sender, t, get_adapter, cfg)

    s = settings()
    p = TraceParams(depth, s.trace_fanout, s.trace_min_usd, s.trace_max_edges, s.trace_window_days, s.trace_back_depth)
    t0 = time.monotonic()
    res = await trace(seeds, since, p, label_index(), get_adapter, cfg, bridge_resolver=bridges.resolve, fallback=fallback)
    secs = time.monotonic() - t0
    top = next((d for d in score(res, since, cfg, lambda e: (1.0, "")) if d.role == "off_ramp"), None)
    return {"seconds": round(secs, 1), "addresses": len(res.nodes), "links": len(res.edges),
            "forward_addresses": sum(1 for n in res.nodes.values() if n.depth >= 0),
            "transactions": sum(e.tx_count for e in res.edges.values()),
            "chains": list(dict.fromkeys(n.chain for n in sorted(res.nodes.values(), key=lambda n: n.depth) if n.depth >= 0)),
            "cross_chain_hops": len(res.crosschain),
            "top_vasp": top.vasp_name if top else None, "confidence": round(top.confidence, 2) if top else None,
            "hops": top.hops if top else None}


async def main() -> None:
    init_db()
    seed_all()
    cases = json.loads((BACKEND_DIR / "data" / "demo_cases.json").read_text(encoding="utf-8"))["cases"]
    rows = []
    if "--sweep-only" in sys.argv:  # reuse the measured cold / warm rows; redo only the (warm) depth sweep
        rows = json.loads((ROOT_DIR / "docs" / "benchmark.json").read_text(encoding="utf-8"))["cases"]
        cases = []
    for c in cases:
        seeds = []
        for w in c["wallets"]:
            chain = w.get("chain") or detect_chain(w["address"])
            seeds.append((chain, normalize_address(chain, w["address"])))
        since = datetime.fromisoformat(c["fraud_time"].replace("Z", "+00:00"))
        cold = await run(seeds, since)
        warm = await run(seeds, since)
        rows.append({"case": c["title"], "seed_chain": seeds[0][0], "cold": cold, "warm": warm})
        print(f"{c['title'][:50]:<50} cold {cold['seconds']:>6}s warm {warm['seconds']:>5}s  {cold['addresses']} addr "
              f"{cold['chains']} hops={cold['cross_chain_hops']} -> {cold['top_vasp']} {cold['confidence']}")

    # depth sweep on the widest demo case: how the bounded trace grows with depth (warm cache = engine cost only)
    all_cases = json.loads((BACKEND_DIR / "data" / "demo_cases.json").read_text(encoding="utf-8"))["cases"]
    widest = max(range(len(rows)), key=lambda i: rows[i]["cold"]["addresses"])
    c0 = all_cases[widest]
    ch = c0["wallets"][0].get("chain") or detect_chain(c0["wallets"][0]["address"])
    seeds0 = [(ch, normalize_address(ch, c0["wallets"][0]["address"]))]
    since0 = datetime.fromisoformat(c0["fraud_time"].replace("Z", "+00:00"))
    sweep = []
    for d in range(1, 6):
        r = await run(seeds0, since0, depth=d)
        sweep.append({"depth": d, "addresses": r["addresses"], "forward_addresses": r["forward_addresses"],
                      "links": r["links"], "seconds": r["seconds"],
                      "fanout_bound_one_chain": sum(settings().trace_fanout ** k for k in range(d + 1))})

    colds = [r["cold"]["seconds"] for r in rows]
    warms = [r["warm"]["seconds"] for r in rows]
    out = {"run_at": datetime.now(timezone.utc).isoformat(), "cases": rows, "depth_sweep": sweep,
           "median_cold_seconds": statistics.median(colds), "median_warm_seconds": statistics.median(warms),
           "max_cold_seconds": max(colds)}
    (ROOT_DIR / "docs" / "benchmark.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    md = ["# BitTrail trace-time benchmark", "",
          f"Run {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC on live public APIs, free tiers, no API keys "
          f"(TronGrid, mempool.space / blockstream.info, Blockscout v2, Solana public RPC, LI.FI / THORChain / deBridge / "
          f"Wormholescan). "
          f"Cold = empty API cache; warm = the same trace again (every response cached, as for re-traces and DEMO_MODE).", "",
          f"**Median: {out['median_cold_seconds']} s cold, {out['median_warm_seconds']} s warm. Slowest cold trace: "
          f"{out['max_cold_seconds']} s.**", "",
          "| Case | Chains | Addresses | Cross-chain hops | Nearest VASP | Cold (s) | Warm (s) |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        c = r["cold"]
        md.append(f"| {r['case']} | {' -> '.join(c['chains'])} | {c['addresses']} | {c['cross_chain_hops']} | "
                  f"{c['top_vasp'] or '-'}{f' ({c['confidence']})' if c['top_vasp'] else ''} | {c['seconds']} | {r['warm']['seconds']} |")
    md += ["", f"## Depth sweep ({c0['title']}, warm cache)", "",
           "Fan-out 5 bounds one chain's forward trace at 1 + 5 + 25 + ... addresses per seed; real trails stay far below "
           "it because most wallets pay fewer than five recipients and exchanges, bridges and mixers end a branch. Bridge "
           "destinations (a new chain) and exchange hot wallets reached by a sweep add addresses on top; the 2,000-link "
           "cap bounds the total. 'All addresses' also includes the 2-hop backward (on-ramp) trace.", "",
           "| Depth | Forward addresses | All addresses | Links | Fan-out bound (one chain) | Seconds (warm) |",
           "| --- | --- | --- | --- | --- | --- |"]
    md += [f"| {s['depth']} | {s['forward_addresses']} | {s['addresses']} | {s['links']} | {s['fanout_bound_one_chain']} | "
           f"{s['seconds']} |" for s in sweep]
    (ROOT_DIR / "docs" / "benchmark.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    asyncio.run(main())
