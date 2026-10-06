# BitTrail — Build Phases

Status: Draft v0.1. Team of 6. Target: a deployable MVP in **7 working days**, with a **48-hour cut** for a screening video.
Roles: **A** chain adapters · **B** trace engine and scoring · **C** labels, heuristics, evaluation · **D** frontend · **E** cases, Sahyog mock, reports · **F** deploy, demo data, video, deck.

Each phase ends with an **exit check**. Don't start the next phase's "nice to have" until the exit check passes.

---

## Phase 0 — Setup (Day 0, ~4 h)

| Owner | Task |
|---|---|
| F | Monorepo (`backend/`, `frontend/`, `docs/`), `.env.example`, Docker Compose (api + db + web), CI deploy to Vercel + Railway |
| B | FastAPI skeleton, config loader, `/health`, Alembic set up |
| E | SQLAlchemy models for `cases`, `case_wallets`, `users`, `audit_log`; seed demo users |
| A | `Transfer` dataclass + `ChainAdapter` protocol + address→chain detection with tests |
| C | Scripts folder; download raw label sources into `data/label_seeds/` |
| D | Vite + React + Tailwind + shadcn; routes and layout; API client |

**Exit check:** both apps deploy from `main`; `/health` is green in production; the login page renders.

---

## Phase 1 — Data foundations (Day 1)

| Owner | Task |
|---|---|
| A | Tron adapter (TRC-20 + TRX, in/out, pagination) + read-through `api_cache` + `DEMO_MODE` |
| C | `load_labels.py`: DefiLlama exchange wallets, OFAC, Etherscan/Tronscan label dumps → `labels`; `vasp_registry.json` → `vasps` |
| F | Pick **5 demo cases + 2 spares** (OFAC / public hack / Chainabuse); verify by hand that each reaches a labelled VASP in ≤ 5 hops; include 2 cases that share a deposit address |
| B | Trace loop against fixture JSON (no network) with limits and value splitting |
| E | `POST/GET /cases` with wallets; audit writes |
| D | Case intake form + case list |

**Exit check:** `labels` has ≥ 5,000 rows across Tron and ETH; the Tron adapter returns real transfers for a demo address; the trace passes its fixture tests.

---

## Phase 2 — First end-to-end trace (Day 2)

| Owner | Task |
|---|---|
| A | EVM adapter (Etherscan API V2: ETH + Polygon) + price table (daily USD) |
| B | Trace jobs (`trace_jobs`, background task, progress) wired to the real adapters; writes `trace_nodes` / `trace_edges` |
| C | Classifier: label lookup + deposit-sweep rule + service-like rule + mixer/bridge stops; `heuristics.yaml` |
| D | Case workspace: Cytoscape graph (legend, edge width = value share), job progress bar |
| E | `GET /cases/{id}/graph` in Cytoscape format |
| F | Pre-warm the cache for demo cases; smoke test in production |

**Exit check:** in production, paste a demo Tron wallet → the graph renders within 60 s → at least one teal VASP node appears.

---

## Phase 3 — Attribution (Day 3)

| Owner | Task |
|---|---|
| B | Scorer (noisy-OR, path factor, actionability, rank score), `candidates` table, backward trace (on-ramp) |
| C | Unit tests on known deposit addresses; tune thresholds; external-tag signal from Tronscan |
| D | Ranked VASP panel (confidence, value share, actionability, reasons, tx hashes, funds status); Sankey tab |
| E | Evidence report as HTML (Jinja2) |
| A | Bitcoin adapter (mempool.space; follow the largest outputs) |

**Exit check:** each demo case shows the expected VASP at rank 1 with ≥ 3 reasons; the mixer branch shows as stopped.

---

## Phase 4 — Action layer (Day 4)

| Owner | Task |
|---|---|
| E | Canonical manifest + SHA-256; WeasyPrint PDF (hash on every page, BSA §63 certificate template); notice templates (Section 94 BNSS disclosure, freeze); mock Sahyog send + reference number |
| D | Report preview + download; "Generate request" flow; record the VASP's Sahyog reply (the `vasp` role and inbox were later removed: that side is Sahyog's) |
| B | Cross-case correlator: `address_case_index`, `case_links`, banner API |
| C | Labels flywheel: VASP confirm → verified label → re-score open cases |
| A | Harden adapters: retries, backoff, rate-limit handling |

**Exit check:** full chain works — trace → report PDF (hash matches) → notice → VASP confirms → the label becomes verified → case 2's confidence rises.

---

## Phase 5 — Monitoring and proof (Day 5)

| Owner | Task |
|---|---|
| B + A | Watch poller (5 min), `watch_items`, `alerts`; "funds still at deposit" status |
| D | Alerts feed, dashboard (cases, value traced, top VASPs, open requests), linked-case banner |
| C | `eval_hide_and_seek.py`: hide N labelled deposit addresses → precision@1; write the result to `docs/eval.md` for the deck |
| E | Optional LLM case narrative (template fallback) |
| F | Error states, empty states, loading skeletons; cross-browser check |

**Exit check:** an alert appears for a watched address (real or simulated tx); the dashboard numbers are right; a precision@1 number exists.

---

## Phase 6 — Hardening (Day 6) · CODE FREEZE at end of day

| Owner | Task |
|---|---|
| All | Bug bash against the PRD acceptance criteria |
| F | Pre-warm every demo and spare case; test `DEMO_MODE=1` fully offline; Docker Compose fallback on a laptop |
| A/B | Performance: every demo trace under 60 s warm |
| D | Polish: legend, tooltips, copy-to-clipboard tx hashes, explorer links |

**Exit check:** all 7 PRD acceptance criteria pass in production **and** offline.

---

## Phase 7 — Demo assets (Day 7)

| Owner | Task |
|---|---|
| F + D | 2–3 min demo video following the script (intake → graph → rank → freeze window → cross-case → notice → flywheel) |
| F | Screenshots into the deck; add the precision@1 and timing numbers |
| All | Rehearse the 5 judge questions (sweep pattern, value-weighted nearest, mixers and bridges, LLM role, evaluation) |

**Exit check:** video recorded; live URL shared; every member can explain the 5 answers.

---

## 48-hour cut (screening-only)

| Hours | Scope |
|---|---|
| 0–12 | Tron adapter + cache · labels (DefiLlama + OFAC) · forward trace |
| 12–30 | Deposit-sweep rule + scorer · graph view + ranked list |
| 30–40 | Evidence PDF + hash · notice template · deploy |
| 40–48 | Pre-warm 2 demo cases · record video |

Deferred to slides: EVM/BTC, backward trace, cross-case, alerts, flywheel.

---

## After the MVP (finale / pilot roadmap)

v0.3 (Oct 2026) pulled parts of P8 and P9 forward at the team's request, so the prototype shows everything the idea
deck claims: keyless Ethereum / Polygon (Blockscout), multi-chain seeds, bridge / swap resolution through LI.FI,
THORChain Midgard, deBridge and Wormholescan, and an unconfirmed same-address fallback. The graph stays NetworkX in
memory (team decision: no Neo4j). Still open below: BNB Chain without a paid key, Arbitrum / Base, ML, worker queue,
bulk history.

| Phase | Adds |
|---|---|
| P8 — More chains | ~~Solana~~ (done; Helius via `SOLANA_RPC_URL`), BNB Chain without a paid key (BSCTrace / NodeReal), Arbitrum/Base via EVM adapter |
| P9 — Cross-chain | ~~Bridge decoding (LI.FI status, Wormholescan, THORChain Midgard, deBridge)~~ (done in v0.3); instant-exchanger (FixedFloat / ChangeNOW) labels; amount/time matching beyond same-address |
| P10 — ML | GraphSAGE on Elliptic++ / BABD-13 + verified flywheel labels as an extra scoring signal |
| P11 — Scale | Neo4j for the cross-case graph; worker queue (Celery / Arq); ClickHouse / BigQuery for bulk history |
| P12 — Integration | Real Sahyog API, I4C Suspect Registry push, Samanvaya linkage, SSO |
| P13 — Deployment | On-prem at I4C / NIC; local LLM via vLLM; security audit |

## Risk log

| Risk | Owner | Mitigation |
|---|---|---|
| API rate limits | A | Cache everything; demo mode; pre-warm |
| A demo trace doesn't reach a VASP | F | Verified on day 1; 2 spares |
| Labels missing for a VASP | C | Add from exchange proof-of-reserves posts; flywheel |
| Bitcoin complexity | A | Largest-output rule; "change detection: next phase" |
| Deployment failure on demo day | F | Docker Compose laptop fallback + recorded video |
| Scope creep | Everyone | Anything not in the demo script waits until after Day 6 |
