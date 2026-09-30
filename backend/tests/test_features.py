"""Tests for explainability, investigation memory, exchange clusters, cross-chain continuity, typologies, Solana parsing."""
import asyncio
from datetime import timedelta

from app.adapters.base import AdapterUnavailable
from app.adapters.solana import SolanaAdapter
from app.engine.explain import compare, confidence, contributions, what_if
from app.engine.model import TraceParams
from app.engine.score import score
from app.engine.trace import trace
from app.engine.typology import analyze
from app.labels.index import LabelIndex, LabelRec
from tests.test_engine import CFG, LABELS, T0, FakeAdapter, run, tx


def _tx(chain, frm, to, usd, minutes):
    t = tx(frm, to, usd, minutes)
    t.chain = chain
    return t


def test_contributions_sum_to_confidence():
    sig = {"label_tier": 0.8, "sweep": 1.0, "value": 0.9, "recency": 1.0}
    conf = confidence(sig, CFG["weights"], 1.0)
    parts = contributions(sig, CFG["weights"], 1.0)
    assert abs(sum(p["points"] for p in parts) - conf * 100) < 0.5
    assert parts[0]["points"] >= parts[-1]["points"]  # sorted, largest first


def test_what_if_and_compare():
    sig = {"label_tier": 0.8, "value": 0.5}
    scenarios = what_if(sig, CFG["weights"], 1.0, CFG)
    confirm = next(s for s in scenarios if "confirms" in s["scenario"])
    mixer = next(s for s in scenarios if "mixer" in s["scenario"])
    assert confirm["delta"] > 0 and mixer["confidence"] == 0.0
    rows = compare(contributions(sig, CFG["weights"], 1.0), contributions({"label_tier": 0.6}, CFG["weights"], 1.0))
    assert any(r["factor"] == "value" and r["gap"] > 0 for r in rows)


def test_history_factor_raises_confidence():
    res = run()
    base = next(d for d in score(res, T0, CFG, lambda e: (1.0, "t")) if d.role == "off_ramp")
    hist = next(d for d in score(res, T0, CFG, lambda e: (1.0, "t"), lambda c, a, e: (1.0, "seen before"))
                if d.role == "off_ramp")
    assert hist.confidence > base.confidence and "seen before" in hist.reasons
    assert hist.explain["contributions"] and hist.explain["evidence"]["transactions"] >= 2


def test_exchange_cluster_inference():
    graph = [tx("SUSPECT", "W", 5000, 10), tx("W", "HOT_BIN", 3500, 20), tx("W", "O1", 400, 21), tx("W", "O2", 400, 22),
             tx("W", "O3", 400, 23), tx("W", "O4", 300, 24)]
    res = run(graph)
    w = res.nodes["tron:W"]
    assert w.kind == "vasp_hot" and w.entity == "Binance" and w.label_source == "heuristic:exchange_cluster"
    top = next(d for d in score(res, T0, CFG, lambda e: (1.0, "t")) if d.role == "off_ramp")
    assert top.vasp_name == "Binance" and top.address == "W"


def test_cross_chain_continuity_via_bridge():
    labels = LabelIndex({("ethereum", "BRIDGE"): [LabelRec("bridge", "TestBridge", "curated", "t")],
                         ("polygon", "HOT_P"): [LabelRec("vasp_hot", "Binance", "curated", "t")]})
    eth = FakeAdapter([_tx("ethereum", "SUSPECT", "BRIDGE", 1000, 10)])
    pol = FakeAdapter([_tx("polygon", "DEST", "DEP2", 990, 30), _tx("polygon", "DEP2", "HOT_P", 990, 35)])
    adapters = {"ethereum": eth, "polygon": pol}

    def adapter_for(c):
        if c not in adapters:
            raise AdapterUnavailable(c)
        return adapters[c]

    async def resolver(chain, txs):
        return {"dest_chain": "polygon", "dest_address": "DEST", "dest_tx": "0xdest", "usd_in": 1000, "usd_out": 995,
                "ts_in": T0 + timedelta(minutes=10), "ts_out": T0 + timedelta(minutes=12), "tool": "testbridge"}

    res = asyncio.run(trace([("ethereum", "SUSPECT")], T0, TraceParams(), labels, adapter_for, CFG, None, resolver))
    b = res.nodes["ethereum:BRIDGE"]
    assert b.stats["continuity"] > 0.9
    assert res.nodes["polygon:DEP2"].kind == "vasp_deposit"
    off = next(d for d in score(res, T0, CFG, lambda e: (1.0, "t")) if d.role == "off_ramp")
    assert off.chain == "polygon" and off.vasp_name == "Binance" and 0.9 < off.signals["path_factor"] < 1.0
    a = analyze(res, T0, [off], 0, CFG)
    assert any(t["code"] == "chain_switching" for t in a["typologies"])
    assert next(x for x in a["risk"]["axes"] if x["key"] == "cross_chain")["score"] >= 80


def test_typologies_splitting_and_rapid_movement():
    graph = [tx("SUSPECT", "A", 3000, 10), tx("A", "B", 2990, 15), tx("B", "C1", 1000, 20), tx("B", "C2", 1000, 21),
             tx("B", "C3", 990, 22)]
    res = run(graph)
    a = analyze(res, T0, [], 0, CFG)
    codes = {t["code"] for t in a["typologies"]}
    assert "splitting" in codes and "rapid_movement" in codes
    assert a["risk"]["level"] in ("low", "medium", "high", "critical") and len(a["risk"]["axes"]) == 6


def test_solana_balance_delta_parsing():
    tx_json = {"blockTime": 1767225600, "slot": 1, "meta": {"err": None, "innerInstructions": [],
               "preTokenBalances": [{"accountIndex": 1, "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "owner": "ALICE",
                                     "uiTokenAmount": {"amount": "5000000", "decimals": 6}},
                                    {"accountIndex": 2, "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "owner": "BOB",
                                     "uiTokenAmount": {"amount": "0", "decimals": 6}}],
               "postTokenBalances": [{"accountIndex": 1, "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "owner": "ALICE",
                                      "uiTokenAmount": {"amount": "1000000", "decimals": 6}},
                                     {"accountIndex": 2, "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "owner": "BOB",
                                      "uiTokenAmount": {"amount": "4000000", "decimals": 6}}]},
               "transaction": {"message": {"instructions": []}}}
    ad = SolanaAdapter()

    async def fake_rpc(method, params, ttl):
        return tx_json

    ad._rpc = fake_rpc
    out = asyncio.run(ad._parse("SIG"))
    assert len(out) == 1 and out[0].from_address == "ALICE" and out[0].to_address == "BOB" and out[0].amount_usd == 4.0
