"""Download public label sources and normalise them into seed CSVs.

Sources
- Dune Spellbook CEX address lists (Tron, Bitcoin, EVM chains)  -> label_seeds/spellbook_cex.csv
- OFAC SDN list (official XML): every "Digital Currency Address", with the SDN entity name and its sanctions
  programs (CYBER2 = cybercrime / ransomware, SDGT / FTO = terrorism, DPRK* ...)   -> label_seeds/ofac.csv

Run:  python scripts/fetch_label_sources.py [spellbook] [ofac]     (default: both)
The CSVs are committed so the app can seed labels without network access.
"""
from __future__ import annotations

import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

SPELLBOOK = "https://raw.githubusercontent.com/duneanalytics/spellbook/main/dbt_subprojects/hourly_spellbook/models/_sector/cex/addresses/chains"
SDN_XML = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
SDN_NS = {"s": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML"}
OUT = Path(__file__).resolve().parents[1] / "data" / "label_seeds"
FIELDS = ["chain", "address", "type", "entity_name", "tier", "source", "source_ref"]

TRON_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
BTC_RE = re.compile(r"^(bc1[0-9a-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM_CHAINS = ["ethereum", "polygon", "bsc"]

# ('tron', 'T...', 'Binance', 'Binance 1', ...)   or   (0xabc..., 'Binance', 'Binance 1', ...)
TUPLE_RE = re.compile(r"\(\s*(?:'(?P<chain>[a-z_]+)'\s*,\s*)?'?(?P<addr>[0-9A-Za-z]+)'?\s*,\s*'(?P<name>[^']*)'\s*,\s*'(?P<distinct>[^']*)'")


def fetch(url: str) -> str:
    r = httpx.get(url, timeout=60, follow_redirects=True)
    r.raise_for_status()
    return r.text


def spellbook_rows() -> list[dict]:
    rows: list[dict] = []
    files = {
        "tron": ("tron/cex_tron_addresses.sql", ["tron"], TRON_RE),
        "bitcoin": ("bitcoin/cex_bitcoin_addresses.sql", ["bitcoin"], BTC_RE),
        "ethereum": ("ethereum/cex_ethereum_addresses.sql", ["ethereum"], EVM_RE),
        "polygon": ("polygon/cex_polygon_addresses.sql", ["polygon"], EVM_RE),
        "solana": ("solana/cex_solana_addresses.sql", ["solana"], SOL_RE),
        # generic list that applies to every EVM chain (BNB Chain's own file just references it)
        "evms": ("cex_evms_addresses.sql", EVM_CHAINS, EVM_RE),
    }
    for key, (path, chains, addr_re) in files.items():
        text = fetch(f"{SPELLBOOK}/{path}")
        n = 0
        for m in TUPLE_RE.finditer(text):
            addr = m.group("addr")
            if not addr_re.match(addr):
                continue
            if addr.startswith("0x"):
                addr = addr.lower()
            for chain in chains:
                rows.append({
                    "chain": chain, "address": addr, "type": "vasp_hot",
                    "entity_name": m.group("name").strip(), "tier": "curated",
                    "source": "dune_spellbook", "source_ref": f"{path} :: {m.group('distinct')}",
                })
            n += 1
        print(f"spellbook {key}: {n} addresses", file=sys.stderr)
    return rows


def ofac_rows() -> list[dict]:
    root = ET.fromstring(fetch(SDN_XML).encode("utf-8"))
    published = root.findtext("s:publshInformation/s:Publish_Date", default="", namespaces=SDN_NS)
    rows: list[dict] = []
    for e in root.findall("s:sdnEntry", SDN_NS):
        ids = [i for i in e.findall("s:idList/s:id", SDN_NS)
               if (i.findtext("s:idType", default="", namespaces=SDN_NS)).startswith("Digital Currency Address")]
        if not ids:
            continue
        name = " ".join(x for x in (e.findtext("s:firstName", default="", namespaces=SDN_NS),
                                    e.findtext("s:lastName", default="", namespaces=SDN_NS)) if x).strip()
        programs = ",".join(p.text for p in e.findall("s:programList/s:program", SDN_NS) if p.text)
        uid = e.findtext("s:uid", default="", namespaces=SDN_NS)
        for i in ids:
            asset = i.findtext("s:idType", default="", namespaces=SDN_NS).replace("Digital Currency Address - ", "")
            addr = (i.findtext("s:idNumber", default="", namespaces=SDN_NS) or "").strip()
            if TRON_RE.match(addr):
                chains = ["tron"]
            elif EVM_RE.match(addr):
                addr, chains = addr.lower(), EVM_CHAINS
            elif asset == "SOL" and SOL_RE.match(addr):
                chains = ["solana"]
            elif asset == "XBT" and BTC_RE.match(addr):
                chains = ["bitcoin"]
            else:
                continue  # LTC, XMR, ZEC ... are outside BitTrail's chains
            for chain in chains:
                rows.append({
                    "chain": chain, "address": addr, "type": "sanctioned", "entity_name": name or f"OFAC SDN uid {uid}",
                    "tier": "published", "source": "ofac",
                    "source_ref": f"OFAC SDN uid {uid}; programs {programs}; {asset}; list of {published}",
                })
    print(f"ofac: {len(rows)} rows (SDN list of {published})", file=sys.stderr)
    return rows


def write(name: str, rows: list[dict]) -> None:
    seen, unique = set(), []
    for r in rows:
        k = (r["chain"], r["address"], r["type"], r["source"])
        if k not in seen:
            seen.add(k)
            unique.append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(unique)
    print(f"wrote {name}: {len(unique)} rows", file=sys.stderr)


if __name__ == "__main__":
    which = set(sys.argv[1:]) or {"spellbook", "ofac"}
    if "spellbook" in which:
        write("spellbook_cex.csv", spellbook_rows())
    if "ofac" in which:
        write("ofac.csv", ofac_rows())
