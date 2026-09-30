"""Hide-and-seek accuracy test on live Tron data (label ablation).

Ground truth: for a labelled exchange hot wallet H of exchange E, recent senders whose outflow goes >= 90% to H
are E's deposit addresses (the deposit-sweep definition, computed with ALL labels known).
Test: trace from each deposit address D with a label set where
  (a) nothing is hidden             -> baseline P@1 (sanity check of the pipeline)
  (b) H's own label is hidden       -> can BitTrail still name E? (via other labels / exchange-cluster rule)
Metrics: Precision@1 (top off-ramp VASP == E), coverage (any VASP found), mean confidence, seconds per trace.

  python scripts/eval_hide_and_seek.py [per_hot_wallet=6]
Writes docs/eval.md.
"""
import asyncio
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters import get_adapter  # noqa: E402
from app.config import ROOT_DIR, heuristics  # noqa: E402
from app.db import init_db  # noqa: E402
from app.engine.model import TraceParams  # noqa: E402
from app.engine.score import score  # noqa: E402
from app.engine.trace import trace  # noqa: E402
from app.labels.index import LabelIndex, label_index  # noqa: E402
from app.labels.seed import seed_all  # noqa: E402

HOTS = {  # sweep-receiving hot wallets found in the demo research (Dune Spellbook labels)
    "TNXoiAJ3dct8Fjg4M9fkLFh9S2v9TXc32G": "Binance",
    "TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe": "Binance",
    "TU7BbAsb8t371eMijQeiGXsiLvY1vZbsFs": "CoinDCX",
}


async def ground_truth(per_hot: int) -> list[tuple[str, str, str, datetime]]:
    t = get_adapter("tron")
    now = datetime.now(timezone.utc)
    out = []
    for hot, entity in HOTS.items():
        ins = await t.get_transfers(hot, "in", now - timedelta(days=10), None)
        found = 0
        for sender, _ in Counter(x.from_address for x in ins).most_common(40):
            if label_index().primary("tron", sender):
                continue
            outs = await t.get_transfers(sender, "out", now - timedelta(days=10), None)
            usd = sum(o.amount_usd for o in outs)
            to_hot = sum(o.amount_usd for o in outs if o.to_address == hot)
            # real sweeps only: at least $50 actually moved to the hot wallet (skips address-poisoning dust)
            if to_hot >= 50 and to_hot / usd >= 0.9 and len({o.to_address for o in outs}) <= 3:
                first_in = min((o.timestamp for o in outs), default=now) - timedelta(hours=1)
                out.append((sender, entity, hot, first_in))
                found += 1
                if found >= per_hot:
                    break
    return out


def ablated(hidden: str) -> LabelIndex:
    full = label_index()
    return LabelIndex({k: v for k, v in full._rows.items() if k != ("tron", hidden)})


async def run_case(dep: str, entity: str, since: datetime, labels: LabelIndex) -> tuple[str | None, float, float, bool]:
    t0 = time.monotonic()
    res = await trace([("tron", dep)], since, TraceParams(max_depth=3, fanout=5, back_depth=0), labels, get_adapter, heuristics())
    top = next((d for d in score(res, since, heuristics(), lambda e: (1.0, "")) if d.role == "off_ramp"), None)
    flagged = any(n.kind == "unknown_service" for n in res.nodes.values())
    return (top.vasp_name if top else None), (top.confidence if top else 0.0), time.monotonic() - t0, flagged


async def main(per_hot: int) -> None:
    init_db()
    seed_all()
    gt = await ground_truth(per_hot)
    print(f"ground-truth deposit addresses: {len(gt)}")
    rows = {"baseline (all labels)": [], "hot-wallet label hidden": []}
    for dep, entity, hot, since in gt:
        for name, labels in (("baseline (all labels)", label_index()), ("hot-wallet label hidden", ablated(hot))):
            got, conf, secs, flagged = await run_case(dep, entity, since, labels)
            rows[name].append((got == entity, got is not None, conf, secs, flagged or got is not None))
            print(f"  {name:<24} {entity:<8} {dep[:10]} -> {got} conf={conf:.2f} flagged={flagged} {secs:.1f}s")

    lines = ["# BitTrail accuracy test (hide-and-seek, label ablation)", "",
             f"Run: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · live Tron data · {len(gt)} ground-truth deposit addresses "
             f"sweeping into {len(HOTS)} labelled hot wallets (Binance, CoinDCX).", "",
             "Ground truth = senders whose outflow goes at least 90% to one labelled exchange hot wallet (deposit-sweep "
             "definition, all labels known). Test (b) hides that hot wallet's label and checks whether BitTrail still names "
             "the right exchange through other labels and the exchange-cluster rule.", "",
             "| Condition | Precision@1 (right exchange ranked first) | Named any exchange | Named or flagged an unlabelled service | Mean confidence |",
             "| --- | --- | --- | --- | --- |"]
    for name, r in rows.items():
        if not r:
            continue
        p1 = sum(x[0] for x in r) / len(r)
        cov = sum(x[1] for x in r) / len(r)
        flag = sum(x[4] for x in r) / len(r)
        confs = [x[2] for x in r if x[1]]
        lines.append(f"| {name} | {p1:.0%} ({sum(x[0] for x in r)}/{len(r)}) | {cov:.0%} | {flag:.0%} | "
                     f"{statistics.mean(confs) if confs else 0:.2f} |")
    hid = rows["hot-wallet label hidden"]
    named_h = sum(x[1] for x in hid) / len(hid) if hid else 0
    flag_h = sum(x[4] for x in hid) / len(hid) if hid else 0
    lines += ["", f"Reading: with the exchange's labels known, BitTrail ranked the correct exchange first in "
              f"{sum(x[0] for x in rows['baseline (all labels)'])} of {len(rows['baseline (all labels)'])} cases. With the "
              f"receiving hot wallet's label removed it named an exchange in {named_h:.0%} of cases and named or flagged "
              f"the unlabelled wallet for review in {flag_h:.0%}. Exchange hot wallets transact almost only with unlabelled "
              f"addresses, so label coverage is the bottleneck: the VASP-reply labels flywheel and more label sources "
              f"address it.", "",
              "Small sample on live data: treat as indicative, not a benchmark. Re-run with a larger `per_hot_wallet` "
              "for a stronger estimate."]
    (ROOT_DIR / "docs" / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 6))
