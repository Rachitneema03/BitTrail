"""Rule-based laundering typologies and a six-axis risk profile, computed from the trace graph.

Evidence first: every typology names the addresses and transactions it rests on; every risk axis says why it
scored what it did. Scores are rule outputs on this trace, not probabilities.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median

from .classify import short
from .model import CandidateDraft, TraceResult

VASP_KINDS = {"vasp_deposit", "vasp_hot", "vasp_cold"}


def _band(value: float, steps: list[tuple[float, int]], default: int) -> int:
    for limit, score in steps:
        if value <= limit:
            return score
    return default


def rescore(risk: dict, cfg: dict) -> dict:
    """Recompute overall score and level after an axis changed (e.g. a later case linked to this one)."""
    rw, lv = cfg["risk_weights"], cfg["risk_levels"]
    overall = round(sum(a["score"] * rw[a["key"]] for a in risk["axes"]) / sum(rw.values()))
    level = "critical" if overall >= lv["critical"] else "high" if overall >= lv["high"] else "medium" if overall >= lv["medium"] else "low"
    return {**risk, "overall": overall, "level": level}


def analyze(res: TraceResult, fraud_time: datetime, drafts: list[CandidateDraft], links: int, cfg: dict) -> dict:
    t = cfg["typology"]
    fwd = [e for e in res.edges.values() if e.direction in ("forward", "bridge")]
    out_by: dict[str, list] = defaultdict(list)
    in_by: dict[str, list] = defaultdict(list)
    for e in fwd:
        out_by[f"{e.chain}:{e.frm}"].append(e)
        in_by[f"{e.dest_chain}:{e.to}"].append(e)
    nodes = res.nodes
    typologies: list[dict] = []

    def add(code, name, severity, detail, addrs, edges):
        typologies.append({"code": code, "name": name, "severity": severity, "detail": detail,
                           "addresses": addrs[:8], "tx": [h for e in edges for h in e.tx_hashes[:2]][:8]})

    # 1. splitting / fan-out
    for nid, es in out_by.items():
        n = nodes.get(nid)
        if not n or n.kind in VASP_KINDS or len(es) < t["split_min_recipients"]:
            continue
        ts = [e.first_ts for e in es if e.first_ts]
        span_h = (max(ts) - min(ts)).total_seconds() / 3600 if len(ts) > 1 else 0
        if span_h <= t["split_window_hours"]:
            add("splitting", "Fund splitting", "medium",
                f"{short(n.address)} paid {len(es)} traced recipients within {span_h:.1f} h",
                [n.address] + [e.to for e in es], es)

    # 2. consolidation / fan-in (not at exchanges, which consolidate by design)
    for nid, es in in_by.items():
        n = nodes.get(nid)
        srcs = {e.frm for e in es}
        if n and n.depth > 0 and n.kind not in VASP_KINDS and len(srcs) >= 2:
            add("consolidation", "Consolidation", "medium",
                f"{short(n.address)} gathered funds from {len(srcs)} traced wallets", [n.address, *srcs], es)

    # 3. rapid movement: hops made soon after the funds arrived
    delays, rapid = [], []
    for e in fwd:
        src = nodes.get(f"{e.chain}:{e.frm}")
        if src and src.depth > 0 and src.arrival and e.first_ts:
            m = (e.first_ts - src.arrival).total_seconds() / 60
            if m >= 0:
                delays.append(m)
                if m <= t["rapid_hop_minutes"]:
                    rapid.append((e, m))
    if len(rapid) >= t["rapid_min_hops"]:
        fastest = min(m for _, m in rapid)
        add("rapid_movement", "Rapid movement", "high",
            f"{len(rapid)} hops each made within {t['rapid_hop_minutes']} min of the funds arriving (fastest {fastest:.0f} min)",
            [e.frm for e, _ in rapid], [e for e, _ in rapid])

    # 4. multi-hop layering on the path to the exchange (or deep trails without one)
    off = [d for d in drafts if d.role == "off_ramp"]
    inter = max((len(d.path) - 2 for d in off), default=0)
    max_depth = max((n.depth for n in nodes.values()), default=0)
    if inter >= t["layering_min_intermediaries"] or (not off and max_depth >= t["layering_min_intermediaries"]):
        add("layering", "Multi-hop layering", "medium",
            f"{max(inter, 0) if off else max_depth} intermediary wallets between the suspect and "
            + ("the exchange" if off else "the end of the trail"), off[0].path if off else [], [])

    # 5. repeated forwarding: pass-through wallets
    passthrough = []
    for nid, es_in in in_by.items():
        n = nodes.get(nid)
        es_out = out_by.get(nid, [])
        if not n or n.depth <= 0 or n.kind in VASP_KINDS or not es_out:
            continue
        usd_in, usd_out = sum(e.amount_usd for e in es_in), sum(e.amount_usd for e in es_out)
        first_in = min((e.first_ts for e in es_in if e.first_ts), default=None)
        first_out = min((e.first_ts for e in es_out if e.first_ts), default=None)
        if usd_in and usd_out / usd_in >= t["passthrough_min_share"] and first_in and first_out \
                and (first_out - first_in).total_seconds() / 3600 <= t["passthrough_max_hours"]:
            passthrough.append((n, es_out))
    if len(passthrough) >= t["passthrough_min_wallets"]:
        add("repeated_forwarding", "Repeated forwarding", "medium",
            f"{len(passthrough)} pass-through wallets forwarded at least {t['passthrough_min_share']:.0%} of what they received "
            f"within {t['passthrough_max_hours']} h", [n.address for n, _ in passthrough], [e for _, es in passthrough for e in es])

    # 6. network switching
    chains = sorted({n.chain for n in nodes.values() if n.depth >= 0})
    bridges = [n for n in nodes.values() if n.kind == "bridge"]
    if len(chains) > 1 or bridges:
        add("chain_switching", "Network switching", "high",
            f"Funds moved across {' -> '.join(chains) if len(chains) > 1 else 'a bridge'}"
            + (f" via {', '.join(b.entity or 'bridge' for b in bridges)}" if bridges else ""),
            [b.address for b in bridges], [e for e in fwd if e.direction == "bridge"])

    # 7. mixer / sanctions exposure
    mixers = [n for n in nodes.values() if n.kind == "mixer"]
    if mixers:
        add("mixer", "Mixer used", "high", f"Funds entered {mixers[0].entity or 'a mixer'}: attribution stops there",
            [m.address for m in mixers], [])
    sanctioned = [n for n in nodes.values() if "sanctioned" in n.flags]
    if sanctioned:
        add("sanctions", "Sanctions exposure", "critical",
            f"{len(sanctioned)} address(es) on the OFAC SDN list touch this trail", [n.address for n in sanctioned], [])

    # ---- risk axes (0-100) ----
    fwd_nodes = [n for n in nodes.values() if n.depth > 0]
    med = median(delays) if delays else None
    velocity = 10 if med is None else _band(med, [(10, 95), (60, 80), (360, 60), (1440, 40)], 20)
    layering = 100 if mixers else _band(inter if off else max_depth, [(0, 10), (1, 30), (2, 50), (3, 70)], 90)
    cross = 85 if (len(chains) > 1 or bridges) else 5
    prolif = _band(len(fwd_nodes), [(3, 15), (6, 35), (12, 55), (25, 75)], 90)
    vasp = round(max((d.value_share for d in off), default=0.0) * 100)
    hist_sig = max((d.signals.get("history", 0) or 0 for d in drafts), default=0)
    historical = 100 if sanctioned else 90 if links else 70 if hist_sig >= 0.6 else 10
    axes = [
        {"key": "velocity", "label": "Fund velocity", "score": velocity,
         "why": f"median hop delay {med:.0f} min" if med is not None else "not enough hops to measure"},
        {"key": "layering", "label": "Layering", "score": layering,
         "why": "mixer on the trail" if mixers else f"{inter if off else max_depth} intermediary wallets"},
        {"key": "cross_chain", "label": "Cross-chain", "score": cross,
         "why": f"{len(chains)} chains" + (", bridge used" if bridges else "")},
        {"key": "proliferation", "label": "Address proliferation", "score": prolif,
         "why": f"{len(fwd_nodes)} downstream addresses traced"},
        {"key": "vasp_exposure", "label": "VASP exposure", "score": vasp,
         "why": f"{vasp}% of traced value reached an exchange"},
        {"key": "historical", "label": "Historical linkage", "score": historical,
         "why": "sanctioned address on trail" if sanctioned else f"{links} cross-case link(s)" if links
         else "seen in earlier cases" if hist_sig >= 0.6 else "no prior cases"},
    ]
    rw = cfg["risk_weights"]
    overall = round(sum(a["score"] * rw[a["key"]] for a in axes) / sum(rw.values()))
    lv = cfg["risk_levels"]
    level = "critical" if overall >= lv["critical"] else "high" if overall >= lv["high"] else "medium" if overall >= lv["medium"] else "low"
    if any(ty["severity"] == "critical" for ty in typologies) and level in ("low", "medium"):
        level = "high"
    return {"risk": {"overall": overall, "level": level, "axes": axes}, "typologies": typologies}
