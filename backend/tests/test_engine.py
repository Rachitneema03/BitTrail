"""Engine tests on a synthetic in-memory graph (no network, no DB)."""
import asyncio
from datetime import datetime, timedelta, timezone

import yaml

from app.adapters.base import Transfer
from app.config import BACKEND_DIR
from app.engine.model import TraceParams
from app.engine.score import noisy_or, score
from app.engine.trace import trace
from app.labels.index import LabelIndex, LabelRec

CFG = yaml.safe_load(open(BACKEND_DIR / "config" / "heuristics.yaml", encoding="utf-8"))
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def tx(frm, to, usd, minutes, h=None):
    return Transfer("tron", h or f"{frm}>{to}@{minutes}", 0, None, T0 + timedelta(minutes=minutes), frm, to,
                    "USDT", "c", str(int(usd * 1e6)), 6, usd, usd)


class FakeAdapter:
    chain = "tron"

    def __init__(self, txs):
        self.txs = txs

    async def get_transfers(self, address, direction, since, until, limit=200):
        if direction == "out":
            r = [t for t in self.txs if t.from_address == address and (not since or t.timestamp >= since)
                 and (not until or t.timestamp <= until)]
            return sorted(r, key=lambda t: t.timestamp)
        r = [t for t in self.txs if t.to_address == address and (not until or t.timestamp <= until)
             and (not since or t.timestamp >= since)]
        return sorted(r, key=lambda t: t.timestamp, reverse=True)

    async def get_info(self, address):
        return None

    async def chain_height(self):
        return 1


LABELS = LabelIndex({
    ("tron", "HOT_BIN"): [LabelRec("vasp_hot", "Binance", "curated", "dune_spellbook")],
    ("tron", "HOT_DCX"): [LabelRec("vasp_hot", "CoinDCX", "curated", "dune_spellbook")],
    ("tron", "MIXER"): [LabelRec("mixer", "SomeMixer", "curated", "test")],
})

GRAPH = [
    # before the fraud: suspect funded by a CoinDCX withdrawal (on-ramp)
    tx("HOT_DCX", "SUSPECT", 500, -600),
    # after the fraud: suspect splits 9000 / 1000
    tx("SUSPECT", "A", 9000, 10),
    tx("SUSPECT", "MIXER", 1000, 12),
    tx("A", "DEP", 8900, 30),
    tx("DEP", "HOT_BIN", 8890, 45),   # deposit sweeps to Binance hot wallet
]


def run(graph=GRAPH, **kw):
    ad = FakeAdapter(graph)
    return asyncio.run(trace([("tron", "SUSPECT")], T0, TraceParams(**kw), LABELS, lambda c: ad, CFG))


def test_deposit_sweep_detected_and_terminal():
    res = run()
    dep = res.nodes["tron:DEP"]
    assert dep.kind == "vasp_deposit" and dep.entity == "Binance" and dep.label_tier == "inferred"
    assert dep.terminal and dep.sweep_share > 0.99
    assert ("tron:DEP", "tron:HOT_BIN", "sweep") in res.edges


def test_mixer_stops_trace():
    res = run()
    m = res.nodes["tron:MIXER"]
    assert m.kind == "mixer" and m.terminal
    assert not any(e[0] == "tron:MIXER" for e in res.edges)


def test_value_split_proportional():
    res = run()
    assert abs(res.nodes["tron:A"].value_share - 0.9) < 1e-6
    assert abs(res.nodes["tron:MIXER"].value_share - 0.1) < 1e-6
    assert abs(res.nodes["tron:DEP"].value_share - 0.9) < 1e-6


def test_scoring_ranks_binance_and_finds_onramp():
    res = run()
    drafts = score(res, T0, CFG, lambda e: (1.0, "test"))
    off = [d for d in drafts if d.role == "off_ramp"]
    on = [d for d in drafts if d.role == "on_ramp"]
    assert off[0].vasp_name == "Binance" and off[0].address == "DEP" and off[0].hops == 2
    assert 0.9 < off[0].confidence <= 1.0
    assert on and on[0].vasp_name == "CoinDCX"
    assert off[0].evidence_tx  # explainable: tx hashes present


def test_depth_limit():
    res = run(max_depth=1)
    assert "tron:DEP" not in res.nodes


def test_noisy_or_bounds():
    assert noisy_or({}, CFG["weights"], 1.0) == 0.0
    assert noisy_or({"label_tier": 1.0}, CFG["weights"], 0.0) == 0.0
    assert 0 < noisy_or({"label_tier": 0.8, "sweep": 1.0}, CFG["weights"], 1.0) < 1
