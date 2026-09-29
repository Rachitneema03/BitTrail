"""Evidence report PDF (fpdf2, pure Python). The manifest hash is printed on every page."""
from __future__ import annotations

from datetime import timezone, timedelta

from fpdf import FPDF

IST = timezone(timedelta(hours=5, minutes=30))
EXPLORER = {"tron": "https://tronscan.org/#/transaction/", "ethereum": "https://etherscan.io/tx/",
            "polygon": "https://polygonscan.com/tx/", "bitcoin": "https://mempool.space/tx/"}


def _t(s) -> str:
    """Core PDF fonts are Latin-1 only."""
    s = str(s if s is not None else "")
    for a, b in {"₹": "INR ", "→": "->", "…": "...", "•": "-", "·": "-", "—": "-", "–": "-", "≥": ">=", "≤": "<=",
                 "×": "x", "“": '"', "”": '"', "’": "'", "‘": "'"}.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


class Report(FPDF):
    def __init__(self, sha: str, case_no: int):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.sha, self.case_no = sha, case_no
        self.set_auto_page_break(True, 18)
        self.set_margins(14, 16, 14)

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(20, 33, 61)
        self.cell(0, 5, _t(f"BitTrail - Evidence Report - Case #{self.case_no}"), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(218, 223, 234)
        self.line(14, self.get_y() + 1, 196, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        self.set_y(-13)
        self.set_font("Courier", "", 7)
        self.set_text_color(90, 100, 119)
        self.cell(0, 4, _t(f"Manifest SHA-256: {self.sha}"), align="L")
        self.cell(0, 4, f"Page {self.page_no()}/{{nb}}", align="R")

    def heading(self, text: str, size: int = 13):
        self.ln(2)
        self.set_font("Helvetica", "B", size)
        self.set_text_color(20, 33, 61)
        self.multi_cell(0, 7, _t(text), new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size: int = 9, style: str = "", color=(63, 74, 94)):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, 4.8, _t(text), new_x="LMARGIN", new_y="NEXT")

    def kv(self, rows: list[tuple[str, str]]):
        for k, v in rows:
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(20, 33, 61)
            self.cell(48, 5.5, _t(k))
            self.set_font("Helvetica", "", 9)
            self.set_text_color(63, 74, 94)
            self.multi_cell(0, 5.5, _t(v), new_x="LMARGIN", new_y="NEXT")


def render(manifest: dict, sha: str, case: dict, candidates: list[dict], nodes: dict, edges: list[dict]) -> bytes:
    r = Report(sha, case["case_no"])
    r.alias_nb_pages()
    r.add_page()
    r.set_font("Helvetica", "B", 20)
    r.set_text_color(20, 33, 61)
    r.cell(0, 10, _t("Blockchain Attribution Evidence Report"), new_x="LMARGIN", new_y="NEXT")
    r.para("Prepared by BitTrail (prototype) for lawful disclosure / freeze request via Sahyog. "
        "All findings are derived from public blockchain data; every hop is listed with its transaction hash.", 9)
    r.heading("1. Case")
    r.kv([("Case no.", f"#{case['case_no']}"), ("FIR no.", case["fir_no"]), ("NCRP ID", case.get("ncrp_id") or "-"),
          ("Police station / State", f"{case.get('police_station') or '-'} / {case.get('state') or '-'}"),
          ("Fraud type", case.get("fraud_type") or "-"),
          ("Fraud reported at", case["fraud_time"].astimezone(IST).strftime("%d %b %Y %H:%M IST")),
          ("Suspect wallet(s)", ", ".join(manifest["seeds"]))])

    r.heading("2. Findings: candidate VASPs")
    off = [c for c in candidates if c["role"] == "off_ramp"]
    on = [c for c in candidates if c["role"] == "on_ramp"]
    if not off:
        r.para("No VASP reached within trace limits. Funds may remain in private wallets (watch-list armed).", style="B")
    for i, c in enumerate(off + on, 1):
        r.set_font("Helvetica", "B", 10)
        r.set_text_color(15, 122, 107)
        role = "Off-ramp (funds deposited to)" if c["role"] == "off_ramp" else "On-ramp (funds withdrawn from)"
        r.multi_cell(0, 6, _t(f"{i}. {c['vasp_name']} - {role}"), new_x="LMARGIN", new_y="NEXT")
        r.kv([("Address", f"{c['chain']}:{c['address']} ({c['address_kind'].replace('_', ' ')})"),
              ("Hops from suspect", str(c["hops"])),
              ("Share of traced value", f"{c['value_share']:.0%}  (approx. USD {c['value_usd']:,.2f})"),
              ("Confidence", f"{c['confidence']:.2f}   Actionability {c['actionability']:.2f}   Rank {c['rank_score']:.3f}"),
              ("Funds status", c["funds_status"].replace("_", " "))])
        r.para("Reasons:", style="B")
        for reason in c["reasons"]:
            r.para(f"  - {reason}")
        if c["evidence_tx"]:
            r.para("Evidence transactions (suspect -> VASP):", style="B")
            r.set_font("Courier", "", 7.5)
            for tx in c["evidence_tx"][:12]:
                r.multi_cell(0, 4, _t(f"  {EXPLORER.get(c['chain'], '')}{tx}"), new_x="LMARGIN", new_y="NEXT")
        r.ln(2)

    r.heading("3. Fund-flow path")
    for e in edges:
        if e["direction"] == "backward":
            continue
        fr, to = nodes.get(e["from"], {}), nodes.get(e["to"], {})
        lab = lambda n: f" [{n.get('entity') or ''} {n.get('kind', '').replace('_', ' ')}]" if n.get("kind") not in ("intermediary", "suspect", None) else ""
        r.set_font("Courier", "", 7.5)
        r.set_text_color(63, 74, 94)
        r.multi_cell(0, 4, _t(f"{e['from']}{lab(fr)} -> {e['to']}{lab(to)}  {e['asset']} USD {e['amount_usd']:,.2f}  "
                              f"({e['tx_count']} tx, share {e['value_share']:.0%}, {e['direction']})"),
                     new_x="LMARGIN", new_y="NEXT")
        r.set_font("Courier", "", 6.5)
        for tx in e["tx_hashes"][:3]:
            r.multi_cell(0, 3.5, _t(f"     tx {tx}"), new_x="LMARGIN", new_y="NEXT")

    r.heading("4. Method and reproducibility")
    t = manifest["trace"]
    r.para(f"Trace parameters: {t['params']}. Chain heights at run time: {t['chain_heights']}. "
        f"Started {t['started_at']}, finished {t['finished_at']} (UTC).")
    r.para("Method: value-weighted forward trace from the suspect wallet(s) (funds after the reported fraud time), "
        "proportional value split at each hop, labels from public sources (Dune Spellbook exchange lists, OFAC SDN), "
        "deposit-address detection from sweep behaviour, and a 2-hop backward trace for on-ramps. Mixers stop the "
        "trace. No attribution decision is made by a language model.")
    r.para("Integrity: the canonical JSON manifest of this report (case, parameters, chain heights, every edge with "
        "transaction hashes, and candidates) hashes to the SHA-256 printed in every page footer. Recomputing the "
        "hash over the manifest (sorted keys, no whitespace, UTF-8) must reproduce it exactly.")
    r.set_font("Courier", "", 8)
    r.multi_cell(0, 4.5, _t(f"SHA-256: {sha}"), new_x="LMARGIN", new_y="NEXT")

    r.add_page()
    r.heading("Certificate under Section 63, Bharatiya Sakshya Adhiniyam, 2023 (template)")
    r.para("[To be completed and signed by the competent officer. Template only - not legal advice.]", style="I")
    r.para("I, ______________________ (name, designation), do hereby certify that:\n"
        "1. The electronic record annexed hereto, namely the BitTrail Evidence Report for Case "
        f"#{case['case_no']} (FIR {case['fir_no']}), was produced by the computer system described below in the "
        "ordinary course of activities.\n"
        "2. The report is derived from public blockchain records retrieved via the APIs listed in Section 4, at the "
        "chain heights stated therein.\n"
        f"3. The SHA-256 hash value of the report manifest is {sha}.\n"
        "4. During the relevant period the computer system was operating properly, and the information contained in "
        "the electronic record reproduces or is derived from such information.\n\n"
        "Place: ______________   Date: ______________\n\nSignature: ______________________\n"
        "Name / Designation / Seal: ______________________", 9)
    return bytes(r.output())
