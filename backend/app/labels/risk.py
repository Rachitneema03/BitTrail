"""High-risk categories from cited sources (never inferred): OFAC SDN sanctions programs -> plain-language category.

The PS asks for alerts on wallets linked to ransomware, darknet, terrorism financing and fraud ecosystems. OFAC's
program codes say why an address was designated; we translate the code, we do not guess.
"""
from __future__ import annotations

import re

# (code, label, severity) per OFAC program prefix / code
PROGRAMS: list[tuple[str, tuple[str, str, str]]] = [
    ("CYBER", ("cybercrime", "Cybercrime / ransomware", "critical")),
    ("SDGT", ("terror_financing", "Terrorism financing", "critical")),
    ("FTO", ("terror_financing", "Terrorism financing", "critical")),
    ("DPRK", ("dprk", "DPRK state hacking / proliferation financing", "critical")),
    ("NPWMD", ("proliferation", "WMD proliferation financing", "critical")),
    ("ILLICIT-DRUGS", ("narcotics", "Narcotics trafficking", "high")),
    ("SDNTK", ("narcotics", "Narcotics trafficking", "high")),
    ("TCO", ("organised_crime", "Transnational organised crime", "high")),
    ("RUSSIA", ("sanctions_evasion", "Russia sanctions evasion", "high")),
    ("UKRAINE", ("sanctions_evasion", "Russia sanctions evasion", "high")),
    ("CAATSA", ("sanctions_evasion", "Russia sanctions evasion", "high")),
    ("IRAN", ("iran", "Iran sanctions", "high")),
    ("IFSR", ("iran", "Iran sanctions", "high")),
    ("IRGC", ("iran", "Iran sanctions", "high")),
    ("HRIT", ("iran", "Iran sanctions", "high")),
    ("ELECTION", ("election_interference", "Foreign election interference", "high")),
]
# SDN entity names that are darknet markets (the name is OFAC's; the category is the plain-language reading of it)
DARKNET_NAMES = ("HYDRA MARKET",)


def programs_of(source_ref: str | None) -> list[str]:
    m = re.search(r"programs ([^;]+)", source_ref or "")
    return [p.strip() for p in m.group(1).split(",")] if m else []


def categories(entity: str | None, source_ref: str | None) -> list[dict]:
    out: dict[str, dict] = {}
    for p in programs_of(source_ref):
        for prefix, (code, label, sev) in PROGRAMS:
            if p.upper().startswith(prefix):
                out.setdefault(code, {"code": code, "label": label, "severity": sev, "programs": []})["programs"].append(p)
                break
    if entity and any(n in entity.upper() for n in DARKNET_NAMES):
        out.setdefault("darknet", {"code": "darknet", "label": "Darknet market", "severity": "critical", "programs": []})
    return list(out.values())
