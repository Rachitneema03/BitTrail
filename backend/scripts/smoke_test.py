"""End-to-end API smoke test of the demo flow.

  python scripts/smoke_test.py http://localhost:8000
Waits for demo traces, then: graph -> report (hash check) -> notice -> send -> VASP confirms via Sahyog -> flywheel -> stats.
"""
import hashlib
import json
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/") + "/api/v1"
PW = "bittrail-demo"


def login(c: httpx.Client, email: str) -> dict:
    r = c.post(f"{BASE}/auth/login", json={"email": email, "password": PW})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def ok(msg: str) -> None:
    print(f"  OK  {msg}")


def main() -> None:
    c = httpx.Client(timeout=120)
    print("health:", c.get(f"{BASE}/health").json())
    io = login(c, "io@bittrail.demo")

    deadline = time.time() + 600
    while True:
        cases = c.get(f"{BASE}/cases", headers=io).json()
        pending = [x for x in cases if x["status"] in ("open", "tracing") and x["top_vasp"] is None]
        tracing = [x for x in cases if x["status"] == "tracing"]
        if not tracing or time.time() > deadline:
            break
        print(f"  … waiting for {len(tracing)} trace(s)")
        time.sleep(5)
    for x in sorted(cases, key=lambda x: x["case_no"]):
        tv = x["top_vasp"] or {}
        print(f"  case #{x['case_no']} {x['status']:<11} links={x['links']} top={tv.get('vasp_name')} "
              f"{tv.get('address_kind')} conf={tv.get('confidence')} funds={tv.get('funds_status')}")
    case = next(x for x in sorted(cases, key=lambda x: x["case_no"]) if x["top_vasp"])
    ok(f"case #{case['case_no']} attributed to {case['top_vasp']['vasp_name']}")

    detail = c.get(f"{BASE}/cases/{case['id']}", headers=io).json()
    g = c.get(f"{BASE}/cases/{case['id']}/graph", headers=io).json()
    assert g["nodes"] and g["edges"], "graph empty"
    ok(f"graph: {len(g['nodes'])} nodes, {len(g['edges'])} edges; links={len(detail['links'])}; alerts={len(detail['alerts'])}")

    rep = c.post(f"{BASE}/cases/{case['id']}/reports", headers=io).json()
    man = c.get(f"{BASE}/reports/{rep['id']}/manifest", headers=io).json()
    recomputed = hashlib.sha256(json.dumps(man["manifest"], sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode()).hexdigest()
    assert recomputed == rep["sha256"] == man["sha256"], "manifest hash mismatch"
    pdf = c.get(f"{BASE}/reports/{rep['id']}.pdf", headers=io)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    ok(f"report sha256 {rep['sha256'][:16]}… verified independently; PDF {len(pdf.content)//1024} KB")

    cand = detail["candidates"][0]
    req = c.post(f"{BASE}/cases/{case['id']}/requests", headers=io,
                 json={"candidate_id": cand["id"], "type": "disclosure_and_freeze"}).json()
    sent = c.post(f"{BASE}/requests/{req['id']}/send", headers=io).json()
    ok(f"notice to {sent['vasp_name']} sent via mock Sahyog: {sent['sahyog_ref']}")

    # the VASP replies on Sahyog; Sahyog pushes the reply back (mock webhook, matched by Sahyog ref)
    ah = login(c, "analyst@bittrail.demo")
    before = cand["confidence"]
    rep2 = c.post(f"{BASE}/sahyog/reply", headers=ah,
                  json={"sahyog_ref": sent["sahyog_ref"], "outcome": "confirmed", "account_ref": "ACC-DEMO-7781",
                        "frozen_amount_usd": 1000}).json()
    assert rep2["status"] == "confirmed", rep2
    after = c.get(f"{BASE}/cases/{case['id']}", headers=io).json()["candidates"][0]["confidence"]
    ok(f"VASP confirmed via Sahyog; flywheel rescored {rep2['rescored_candidates']} candidate(s); confidence {before} -> {after}")

    s = c.get(f"{BASE}/stats", headers=io).json()
    ok(f"stats: {s['cases']} cases, {s['attributed']} attributed, ${s['traced_usd']:,.0f} traced, "
       f"{s['links']} links, {s['verified_labels']} verified labels")
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    main()
