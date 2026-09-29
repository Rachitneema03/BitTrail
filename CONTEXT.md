# BitTrail — Project Context

> Read this first. It is the single source of context for anyone (human or AI assistant) working on this repo.
> Detailed specs: [docs/prd.md](docs/prd.md) · [docs/architecture.md](docs/architecture.md) · [docs/schema.md](docs/schema.md) · [docs/phases.md](docs/phases.md)

## Identity

| | |
|---|---|
| **Solution** | **BitTrail** |
| **Team** | **TrackSense** |
| **Event** | Smart India Hackathon (SIH) 2026 · Software |
| **Problem statement** | **SIH26182** — Automated Attribution of Unknown Cryptocurrency Wallets to Nearest Virtual Asset Service Providers (VASPs) through Blockchain Intelligence APIs |
| **PS owner** | Ministry of Home Affairs — Indian Cyber Crime Coordination Centre (I4C) |
| **Tagline** | Trace • Attribute • Freeze |
| **One line** | Paste a suspect wallet from a Sahyog case → get the nearest exchange (VASP) that can freeze the funds, with confidence, evidence, and a drafted lawful request. |

## The problem in brief

- Scam proceeds in India increasingly move as crypto, mostly **USDT on Tron**. Cyber-fraud losses were ₹22,845.73 Cr in 2024 (MHA, Lok Sabha Q.344, 22 Jul 2025).
- Suspect wallets are **unhosted**, so nobody holds KYC for them. The money eventually passes through a **VASP** (exchange / custodial / P2P) that does hold KYC.
- Police send disclosure and freeze requests through **Sahyog** (I4C portal; 45+ crypto exchanges onboarded) under **Section 94 BNSS**, but they don't know **which VASP** to address.
- Tracing manually hop by hop across chains, mixers and bridges needs experts and time. Meanwhile the funds cash out.
- Real Indian cases (ED 2025–26) show two more patterns: mules **buy USDT on exchange P2P markets** (the on-ramp), and trails that **end in private wallets abroad**.

## What BitTrail does (MVP)

1. **Intake** a case (FIR, NCRP ID, fraud time, wallets) — mock Sahyog.
2. **Trace forward** (value-weighted breadth-first search) and **backward 2 hops** (on-ramp) on **Tron, Ethereum, Polygon, Bitcoin**.
3. **Classify** each address: VASP hot / deposit wallet, mixer, bridge, sanctioned, off-ramp, unknown service, intermediary.
4. **Score and rank** candidate VASPs: `rank = value_share × confidence × actionability`.
5. **Act:** hash-sealed evidence PDF + drafted Section 94 BNSS notice → mock Sahyog → VASP inbox.
6. **Link cases** that share deposit addresses; **alert** when watched funds move.
7. **Labels flywheel:** a VASP confirmation becomes a verified label and re-scores open cases.

**Not in the MVP:** real Sahyog integration, Solana/BNB, bridge decoding, graph neural networks, Neo4j, on-prem LLM.

## Non-negotiable principles

1. **Explainable or it doesn't ship.** Every attribution lists its reasons and transaction hashes. No black-box output.
2. **The LLM never decides attribution.** It may only write narrative text. Decisions come from labels, rules and scores.
3. **Stop at mixers.** Never claim attribution through a mixer; flag and stop.
4. **Reproducible evidence.** Record chain heights / timestamps, cache every API response, and hash the canonical manifest (SHA-256).
5. **Cache everything; demo mode works offline.** `DEMO_MODE=1` serves only from `api_cache`.
6. **Never invent labels or statistics.** Labels come from cited sources, the heuristic rules (marked `inferred`), or VASP confirmation (`verified`).
7. **No real personal data.** Case metadata in the demo is fictional; wallet addresses are public on-chain data.
8. **Append-only audit.** Every mutating action writes to `audit_log`.
9. **Scope discipline.** If it's not in the demo script ([docs/phases.md](docs/phases.md) Phase 7), it waits.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, **FastAPI**, SQLAlchemy 2 + Alembic, httpx (async), Pydantic v2 |
| Graph | **NetworkX** in memory (traces ≤ 2,000 edges) |
| Database | **Supabase Postgres** via the IPv4 session pooler (SQLite when `DATABASE_URL` is unset); schema via `create_all` |
| Jobs | FastAPI background tasks + `trace_jobs` table (no Celery / Redis) |
| Reports | **fpdf2** PDF (pure Python); SHA-256 canonical manifest; Jinja2 for notices |
| Frontend | **Vite + React 19 + TypeScript (strict)**, Tailwind v4, **Cytoscape.js** (graph), **ECharts** (Sankey) |
| Deploy | **One Docker image** (React build served by FastAPI) → **Railway**; DB → Supabase · fallback → `docker compose` |

## External data sources

| Purpose | Source | Env var |
|---|---|---|
| Tron transfers (TRX, USDT-TRC20) | TronGrid | `TRONGRID_API_KEY` |
| Tron address tags | Tronscan | — |
| Ethereum + Polygon | Etherscan API V2 (`chainid=1` / `137`) | `ETHERSCAN_API_KEY` |
| Bitcoin | mempool.space | — |
| Daily USD prices | free price API | `PRICE_API_BASE` |
| Exchange wallets (high confidence) | DefiLlama open-source CEX wallet lists | — |
| Exchange / bridge / mixer labels | Dune Spellbook CEX lists, Etherscan/Tronscan label dumps | — |
| Sanctioned addresses | OFAC SDN crypto address lists | — |
| VASP registry (FIU-IND, Sahyog status) | hand-curated `backend/data/vasp_registry.json` | — |

Known constraint: Etherscan's free tier no longer covers BNB Chain, Base or Optimism.

## Core algorithm (reference values)

**Trace limits** (env `TRACE_*`): max depth 5 · fan-out 5 (top by USD) · min $10 · max 2,000 edges · 90-day window · backward depth 2.

**Classification** (first match wins; thresholds in `backend/config/heuristics.yaml`):
1. mixer → terminal stop · 2. bridge → terminal · 3. sanctioned → flag, continue · 4. labelled VASP → terminal
5. **Deposit-sweep:** ≥ 90% of outflow goes to one `vasp_hot`, ≤ 3 outgoing counterparties, first sweep ≤ 24 h after the traced funds arrive → `vasp_deposit` (inferred)
6. **Service-like:** ≥ 10k txs or ≥ 1k counterparties → `unknown_service`
7. known P2P / fintech → `offramp` · 8. else `intermediary`

**Confidence:** `path_factor × (1 − Π(1 − wᵢ·sᵢ))`

| Signal | Weight |
|---|---|
| label tier | 0.9 |
| sweep | 0.7 |
| external tag | 0.5 |
| value share | 0.4 |
| recency | 0.2 |

`path_factor`: clean 1.0 · bridge 0.7 · mixer 0.

**Actionability:** FIU-IND registered + on Sahyog 1.0 · FIU-IND only 0.9 · Sahyog only 0.85 · foreign VASP with a law-enforcement portal 0.6 · unknown 0.3.

## Repository layout (target)

```
bittrail/                  (repo root = this folder)
  backend/app/{routers,adapters,engine,labels,reports,notices,watch,db}
  backend/config/heuristics.yaml
  backend/data/{vasp_registry.json,demo_cases.json,label_seeds/}
  backend/scripts/{load_labels.py,prewarm_cache.py,eval_hide_and_seek.py}
  frontend/src/{pages,components/graph,components/sankey,api,store}
  docs/{prd,architecture,schema,phases}.md
  docker-compose.yml  .env.example  CONTEXT.md  CLAUDE.md
```

## Key interfaces

- **`Transfer`** — normalised output of every chain adapter: `chain, tx_hash, log_index, block, timestamp, from, to, asset, contract, amount_raw, decimals, amount, amount_usd`.
- **`ChainAdapter`** — `detect(address)`, `get_transfers(address, direction, since, until, limit)`, `get_address_stats(address)`, `get_tags(address)`.
- **Address → chain:** `T…` (34 chars, base58) → tron · `0x` + 40 hex → EVM · `bc1` / `1` / `3` → bitcoin.
- **API base:** `/api/v1` — cases, trace jobs, graph, candidates, links, reports, requests, VASP inbox and replies, alerts, watch, stats, sahyog webhook stub, auth, health. Full list: [architecture.md §6](docs/architecture.md).
- **Roles:** `io` (investigating officer), `analyst` (I4C), `vasp` (simulated exchange officer).

## Coding conventions

- **Python:** type hints everywhere; Pydantic models for API I/O; async I/O for external calls; `ruff` + `black`; `pytest` for the engine (fixtures, no network).
- **TypeScript:** strict mode; API types generated or kept in `frontend/src/api/types.ts`; components in PascalCase.
- **Addresses:** EVM lower-cased; Tron and BTC stored exactly as given. Node IDs in graphs = `"{chain}:{address}"`.
- **Money:** keep the raw on-chain amount plus `amount_usd`; USDT/USDC = $1.
- **Times:** UTC `timestamptz` everywhere; show IST in the UI.
- **Config over constants:** thresholds and weights live in `heuristics.yaml` / env vars, never hard-coded.
- **Every external call goes through the cache layer.** No direct `httpx` calls from engine code.
- **Commits:** small, one feature each; conventional prefixes (`feat:`, `fix:`, `docs:`).

## Glossary

| Term | Meaning |
|---|---|
| **VASP** | Virtual Asset Service Provider: an exchange, custodial wallet, or P2P / fintech platform holding KYC |
| **Unhosted wallet** | A self-custody wallet with no provider, so no KYC |
| **Deposit address** | Per-customer exchange address; funds here identify an account. **The key output.** |
| **Hot wallet** | The exchange's main operational wallet; deposit addresses sweep into it |
| **Sweep** | An automatic transfer from a deposit address to the hot wallet |
| **Hop** | One transfer between addresses |
| **On-ramp / off-ramp** | Where fiat becomes crypto / crypto becomes fiat |
| **Mixer** | A service that pools and shuffles funds to break the trail (e.g. Tornado Cash) |
| **Bridge** | A service that moves assets across chains |
| **Sahyog** | I4C portal for lawful notices to intermediaries (Section 94 BNSS, IT Act §79(3)(b)) |
| **I4C / NCRP / CFCFRMS** | Indian Cyber Crime Coordination Centre / National Cybercrime Reporting Portal / citizen financial fraud reporting system (1930) |
| **Samanvaya / Suspect Registry** | Existing I4C platforms for interstate case linkage / mule identifiers (future integration points) |
| **FIU-IND** | Financial Intelligence Unit–India; VASPs must register under PMLA |
| **BNSS §94 / §106** | Legal basis for production of documents / seizure |
| **BSA §63** | Bharatiya Sakshya Adhiniyam certificate for electronic evidence |

## Demo script (what everything is built toward)

1. Create a case with a real Tron wallet → 2. the graph animates (thickness = value; mixer flagged) → 3. ranked VASP with confidence and reasons → 4. "funds still at deposit" alert → 5. a second case auto-links via a shared deposit address → 6. generate the Section 94 BNSS notice + hashed evidence PDF → send via mock Sahyog → 7. the VASP confirms → the label becomes verified → confidence rises.

## Status

- [x] Research, PPT (6-slide SIH template), PRD, architecture, schema, phase plan
- [x] Prototype v0.1: phases 1–6 built. Tron / BTC live (ETH / Polygon need `ETHERSCAN_API_KEY`), engine + unit tests, full UI, reports, notices, mock Sahyog + VASP inbox, flywheel, cross-case links, watch poller, Supabase, Dockerfile / Railway config
- [x] Verified: `pytest` (6 pass) and `scripts/smoke_test.py` pass on SQLite and on Supabase; UI walkthrough in Edge with no browser errors
- [ ] Not yet: hosted deployment (needs your Railway account), hide-and-seek accuracy evaluation (`eval_hide_and_seek.py`), a third demo case ending at Binance, Docker build tested (Docker isn't installed on the dev machine)

**Demo cases** (`backend/data/demo_cases.json`): real Tron wallets `TKxQN5i…` (Case 1) and `TD1Jp17…` (Case 2) both reach CoinDCX deposit `TADSuFLf…` → linked. Case metadata is fictional.

**Open decisions:** BNB Chain in the MVP? LLM narrative or template only? Is the demo login-gated? (It is now, with one-click demo roles.)
