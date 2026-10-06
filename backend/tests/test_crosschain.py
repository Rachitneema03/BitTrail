"""Tests for v0.3: tracker-detected bridges, multi-chain seeds, adaptive dust, CoinJoin, risk categories, RAG, routing."""
import asyncio
from datetime import timedelta

from app.adapters.base import AdapterUnavailable
from app.adapters.btc import is_coinjoin
from app.engine.model import TraceParams
from app.engine.score import score
from app.engine.trace import trace
from app.engine.typology import analyze
from app.labels.index import LabelIndex, LabelRec
from app.labels.registry import route
from app.labels.risk import categories
from app.models import Vasp
from app.rag import bm25
from tests.test_engine import CFG, LABELS, T0, FakeAdapter, run, tx


def _tx(chain, frm, to, usd, minutes, tags=()):
    t = tx(frm, to, usd, minutes)
    t.chain, t.tags = chain, tags
    return t


def _adapters(**by_chain):
    def adapter_for(c):
        if c not in by_chain:
            raise AdapterUnavailable(c)
        return by_chain[c]
    return adapter_for


def test_unlabelled_bridge_vault_detected_by_tracker_not_followed():
    """A THORChain-style vault looks like a wallet; the tracker identifies it and the trail jumps chains."""
    btc = FakeAdapter([_tx("bitcoin", "SUSPECT", "VAULT", 2000, 10),
                       _tx("bitcoin", "VAULT", "SOMEONE_ELSE", 5000, 20)])  # other people's money: must not follow
    eth = FakeAdapter([_tx("ethereum", "RECV", "DEP", 1990, 30), _tx("ethereum", "DEP", "HOT_E", 1990, 40)])
    labels = LabelIndex({("ethereum", "HOT_E"): [LabelRec("vasp_hot", "Binance", "curated", "t")]})

    async def resolver(chain, txs):
        if chain == "bitcoin" and any(t.to_address == "VAULT" for t in txs):
            return [{"provider": "THORChain Midgard", "tool": "thorchain", "entity": "THORChain", "kind": "swap",
                     "dest_chain": "ethereum", "dest_address": "RECV", "dest_tx": "0xout", "src_tx": "in",
                     "usd_in": 2000, "usd_out": 1995, "ts_in": T0 + timedelta(minutes=10),
                     "ts_out": T0 + timedelta(minutes=12), "asset": "ETH"}]
        return []

    res = asyncio.run(trace([("bitcoin", "SUSPECT")], T0, TraceParams(), labels,
                            _adapters(bitcoin=btc, ethereum=eth), CFG, None, resolver))
    v = res.nodes["bitcoin:VAULT"]
    assert v.kind == "swap_service" and v.entity == "THORChain" and v.label_source.startswith("bridge_tracker")
    assert "bitcoin:SOMEONE_ELSE" not in res.nodes
    assert res.nodes["ethereum:DEP"].kind == "vasp_deposit"
    assert res.crosschain and res.crosschain[0]["to_chain"] == "ethereum" and res.crosschain[0]["continuity"] > 0.9
    off = next(d for d in score(res, T0, CFG, lambda e: (1.0, "t")) if d.role == "off_ramp")
    assert off.chain == "ethereum" and off.explain["evidence"]["chains"] == ["bitcoin", "ethereum"]
    assert "bitcoin -> ethereum" in " ".join(off.reasons)


def test_evm_seed_traced_on_every_active_evm_chain():
    class Probe(FakeAdapter):
        async def has_activity(self, address, since):
            return any(t.from_address == address for t in self.txs)

    eth = Probe([_tx("ethereum", "0xs", "A", 1000, 10)])
    pol = Probe([_tx("polygon", "0xs", "B", 3000, 10)])
    bsc = Probe([])
    res = asyncio.run(trace([("ethereum", "0xs")], T0, TraceParams(), LabelIndex({}),
                            _adapters(ethereum=eth, polygon=pol, bsc=bsc), CFG))
    assert "polygon:0xs" in res.nodes and "bsc:0xs" not in res.nodes
    # seeds weighted by what they sent: 1000 vs 3000
    assert abs(res.nodes["polygon:0xs"].value_share - 0.75) < 1e-6
    assert any("Multi-chain" in n for n in res.notes)


def test_adaptive_dust_filter_and_structuring_guard():
    dusty = [tx("SUSPECT", "A", 10000, 10)] + [tx("SUSPECT", f"P{i}", 0.5, 11 + i) for i in range(5)] + \
            [tx("SUSPECT", "SMALL", 30, 20)]
    res = run(dusty)
    s = res.nodes["tron:SUSPECT"]
    assert "tron:SMALL" not in res.nodes  # $30 < 0.5% of $10,030 -> dust
    assert s.stats["dust_filtered"] == 6 and res.dust["poisoning"] == 5  # five $0.50 transfers = poisoning dust
    assert "address-poisoning" in " ".join(s.reasons)
    # many small transfers carrying most of the value: structuring, not dust
    # 60 x $90 = 21% of $25,400; adaptive floor would be $127, so these would all be "dust"
    smurf = [tx("SUSPECT", f"M{i}", 90, 10 + i) for i in range(60)] + [tx("SUSPECT", "BIG", 20000, 80)]
    res2 = run(smurf, fanout=70)
    assert "structuring" in res2.nodes["tron:SUSPECT"].flags and "tron:M0" in res2.nodes


def test_coinjoin_stops_trace():
    btc = FakeAdapter([_tx("bitcoin", "SUSPECT", "CJOUT", 1000, 10, ("coinjoin",)),
                       _tx("bitcoin", "CJOUT", "HOT", 1000, 20)])
    res = asyncio.run(trace([("bitcoin", "SUSPECT")], T0, TraceParams(), LabelIndex({}), _adapters(bitcoin=btc), CFG))
    mix = [n for n in res.nodes.values() if n.kind == "mixer"]
    assert mix and mix[0].label_source == "heuristic:coinjoin" and mix[0].terminal
    assert "bitcoin:CJOUT" not in res.nodes
    assert any(t["code"] == "mixer" for t in analyze(res, T0, [], 0, CFG)["typologies"])


def test_is_coinjoin_rule():
    eq = [{"value": 100000}] * 6 + [{"value": 7}, {"value": 9}]
    assert is_coinjoin({"vin": [{}] * 6, "vout": eq})
    assert not is_coinjoin({"vin": [{}] * 2, "vout": eq})
    assert not is_coinjoin({"vin": [{}] * 6, "vout": [{"value": i} for i in range(1, 9)]})


def test_sanctions_programs_become_risk_categories():
    cats = {c["code"] for c in categories("ISIL KHORASAN", "OFAC SDN uid 1; programs FTO,SDGT; TRX; list of x")}
    assert cats == {"terror_financing"}
    assert {c["code"] for c in categories("X", "programs CYBER2,RUSSIA-EO14024")} == {"cybercrime", "sanctions_evasion"}
    labels = LabelIndex({**LABELS._rows, ("tron", "A"): [LabelRec("sanctioned", "SOME RANSOMWARE GROUP", "published",
                                                                  "ofac", ref="programs CYBER2")]})
    from tests.test_engine import GRAPH
    ad = FakeAdapter(GRAPH)
    res = asyncio.run(trace([("tron", "SUSPECT")], T0, TraceParams(), labels, lambda c: ad, CFG))
    a = analyze(res, T0, [], 0, CFG)
    assert a["risk"]["level"] == "critical" and a["risk"]["categories"][0]["code"] == "cybercrime"


def test_bm25_prefers_matching_evidence():
    chunks = [{"id": "1", "kind": "candidate", "title": "CoinDCX", "text": "CoinDCX deposit address TADSuFLf sweep"},
              {"id": "2", "kind": "reference", "title": "Section 94", "text": "production of documents notice"},
              {"id": "3", "kind": "transfer", "title": "x", "text": "transfer of 500 USDT"}]
    top = bm25(chunks, "why coindcx deposit?")
    assert top[0][1]["id"] == "1"
    assert bm25(chunks, "section 94 notice")[0][1]["id"] == "2"


def test_deposit_sweeping_into_two_hot_wallets_of_one_exchange():
    labels = LabelIndex({("tron", "HOT_K1"): [LabelRec("vasp_hot", "KuCoin", "curated", "t")],
                         ("tron", "HOT_K2"): [LabelRec("vasp_hot", "KuCoin", "curated", "t")]})
    graph = [tx("SUSPECT", "DEP", 1000, 10), tx("DEP", "HOT_K1", 600, 30), tx("DEP", "HOT_K2", 400, 35)]
    ad = FakeAdapter(graph)
    res = asyncio.run(trace([("tron", "SUSPECT")], T0, TraceParams(), labels, lambda c: ad, CFG))
    dep = res.nodes["tron:DEP"]
    assert dep.kind == "vasp_deposit" and dep.entity == "KuCoin" and dep.sweep_share > 0.99
    assert ("tron:DEP", "tron:HOT_K1", "sweep") in res.edges and ("tron:DEP", "tron:HOT_K2", "sweep") in res.edges


def test_detect_chain_bech32_and_others():
    from app.adapters.base import detect_chain
    assert detect_chain("bc1qg7wuh7umgtwm8r3sspgffc90czsfj9qtjq5psm") == "bitcoin"
    assert detect_chain("bc1p5d7rjq7g6rdk2yhzks9smlaqtedr4dekq08ge8ztwac72sfr9rusxg3297") == "bitcoin"
    assert detect_chain("1BoatSLRHtKNngkdXEeobR76b53LETtpyT") == "bitcoin"
    assert detect_chain("TKxQN5iF6jUGd8h4yuAXYX1oBGciCdWB5P") == "tron"
    assert detect_chain("0x28C6c06298d514Db089934071355E5743bf21d60") == "ethereum"
    assert detect_chain("BhdQMtpohJzUWyaoX9sQrEJvL8NLWaSmzHjXUujfpmbk") == "solana"


def test_route_channels():
    assert route(Vasp(name="A", on_sahyog=True), "A")["channel"] == "sahyog"
    assert route(Vasp(name="B", fiu_ind_registered=True), "B")["channel"] == "sahyog_notice"
    assert route(Vasp(name="C", le_portal_url="https://x"), "C")["channel"] == "le_portal"
    assert route(None, "D")["channel"] == "international"
