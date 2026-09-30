"""Drafted lawful notices (templates; to be reviewed and signed by the officer)."""
from __future__ import annotations

from datetime import timedelta, timezone

from jinja2 import Environment, StrictUndefined

IST = timezone(timedelta(hours=5, minutes=30))

TEMPLATE = """\
**NOTICE UNDER {{ basis }}**
*(Sent via Sahyog Portal, I4C, MHA)*

To: {{ contact }}
{{ vasp }}

From: {{ officer }}, {{ station or "[Police Station]" }}, {{ state or "[State]" }}
FIR No.: {{ fir }}  |  NCRP ID: {{ ncrp or "-" }}  |  BitTrail Case #{{ case_no }}
Date: {{ date }}

**Subject:** {{ subject }}

1. The undersigned is investigating the above case of {{ fraud_type or "cyber fraud" }} reported on {{ fraud_date }}. Blockchain analysis (report attached, manifest SHA-256 `{{ sha or "[generate report]" }}`) shows that proceeds of the offence were {{ "deposited to" if role == "off_ramp" else "withdrawn from" }} your platform through the following {{ chain|capitalize }} address(es):
{% for a in addresses %}
   - `{{ a }}`
{%- endfor %}

2. You are hereby required to produce, within the time permitted by law:
   a. KYC details of the account holder(s) to whom the above address(es) are assigned (name, ID documents, contact, bank accounts linked);
   b. login / IP logs and device details for the account(s);
   c. complete deposit, trade and withdrawal history of the account(s) from {{ fraud_date }} to date, including destination addresses of withdrawals.
{% if freeze %}
3. **Freeze request.** As the funds are proceeds of crime, you are requested to immediately freeze / debit-freeze the virtual digital assets held in the said account(s) and associated with the above address(es), and not permit any withdrawal pending further orders{% if freeze_basis %}, in terms of {{ freeze_basis }}{% endif %}. Please confirm the amount frozen.
{% endif %}
{{ "4" if freeze else "3" }}. Evidence summary: {{ hops }} hop(s) from suspect wallet `{{ suspect }}`; {{ share }} of traced value; confidence {{ confidence }}. Key transactions:
{% for tx in evidence %}
   - `{{ tx }}`
{%- endfor %}
{% if linked %}

{{ "5" if freeze else "4" }}. **Consolidated request.** The same address / account is linked to the following cases, whose trails reach it independently. Please treat this as one request and share the account details once, referencing all of them:
{% for l in linked %}
   - FIR {{ l.fir_no }} ({{ l.state or "State n/a" }}), NCRP {{ l.ncrp_id or "-" }}, BitTrail Case #{{ l.case_no }}
{%- endfor %}
{% endif %}

Please treat this notice as confidential and do not alert the account holder.

{{ officer }}
[Signature / Seal]
"""

env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
_tpl = env.from_string(TEMPLATE)


def render_notice(*, req_type: str, case, candidate, officer: str, contact: str, suspect: str, sha: str | None,
                  linked: list | None = None) -> tuple[str, str]:
    freeze = req_type in ("freeze", "disclosure_and_freeze")
    basis = "SECTION 94, BHARATIYA NAGARIK SURAKSHA SANHITA, 2023" + (" READ WITH SECTION 106" if freeze else "")
    subject = {"disclosure": "Request for disclosure of account information",
               "freeze": "Request to freeze virtual digital assets",
               "disclosure_and_freeze": "Request for disclosure of account information and freezing of virtual digital assets"}[req_type]
    body = _tpl.render(
        basis=basis, contact=contact, vasp=candidate.vasp_name, officer=officer, station=case.police_station,
        state=case.state, fir=case.fir_no, ncrp=case.ncrp_id, case_no=case.case_no,
        date=__import__("datetime").datetime.now(IST).strftime("%d %b %Y"),
        subject=subject, fraud_type=case.fraud_type, fraud_date=case.fraud_time.astimezone(IST).strftime("%d %b %Y"),
        sha=sha, role=candidate.role, chain=candidate.chain, addresses=[candidate.address], freeze=freeze,
        freeze_basis="Section 106 BNSS" if freeze else None, hops=candidate.hops, suspect=suspect,
        share=f"{candidate.value_share:.0%}", confidence=f"{candidate.confidence:.2f}", evidence=candidate.evidence_tx[:6],
        linked=linked or [])
    legal = "Section 94 BNSS" + (" r/w Section 106 BNSS" if freeze else "")
    return body, legal
