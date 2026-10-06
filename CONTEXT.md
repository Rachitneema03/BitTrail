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
2. **Trace forward** (value-weighted breadth-first search) and **backward 2 hops** (on-ramp) on **Tron, Bitcoin, Solana, Ethereum, Polygon, BNB Chain**; **cross-chain** through bridges via the LI.FI status API with a continuity score.
3. **Classify** each address: VASP hot / deposit wallet, exchange cluster (inferred), mixer, bridge, sanctioned, off-ramp, unknown service, intermediary.
4. **Score and rank** candidate VASPs: `rank = value_share × confidence × actionability`, with a factor-by-factor breakdown, "why A not B" and what-if scenarios.
5. **Risk + typologies:** six-axis risk profile and rule-based laundering patterns (splitting, consolidation, rapid movement, layering, repeated forwarding, network switching, mixer, sanctions).
6. **Act:** hash-sealed evidence PDF (timeline, score calculation, patterns, integrity) + drafted Section 94 BNSS notice (optionally consolidated across linked cases) → mock Sahyog. VASPs reply on Sahyog (not in BitTrail); the reply is recorded by the officer or pushed by the mock Sahyog webhook.
7. **Investigation memory:** cases linked by shared addresses, a history factor in scoring, and a labels flywheel (a VASP confirmation becomes a verified label and re-scores open cases).
8. **Monitoring:** watch-list on suspect, deposit and end-point wallets; configurable alerts; timeline + investigation replay.
9. **Sarvam AI (optional):** case summary (English/Hindi), "Ask this case", Hindi notice translation — from computed evidence only.

**Not in the MVP:** real Sahyog integration, graph neural networks, Neo4j, on-prem LLM.

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
| AI | **Sarvam AI** (`sarvam-105b` chat, `sarvam-translate:v1`), optional, narration only |

## External data sources

| Purpose | Source | Env var |
|---|---|---|
| Tron transfers (TRX, USDT-TRC20) | TronGrid (no key needed) | `TRONGRID_API_KEY` (optional) |
| Ethereum + Polygon | Etherscan API V2 if a key is set, else the **Blockscout** public API (no key) | `ETHERSCAN_API_KEY` (optional) |
| BNB Chain | Etherscan V2 paid tier or any Etherscan-compatible API | `ETHERSCAN_BSC`, `BSC_API_BASE` |
| Bitcoin | mempool.space | — |
| Solana | Solana JSON-RPC (public; Helius URL recommended) | `SOLANA_RPC_URL` |
| Cross-chain destinations | LI.FI status (incl. Tron, Bitcoin), THORChain Midgard, deBridge DLN, Wormholescan, all by source tx hash, no keys | `BRIDGE_TRACKER`, `CROSSCHAIN_PROVIDERS`, `THORCHAIN_MIDGARD_URL` |
| Daily USD prices | Binance public daily klines (USDT/USDC = $1) | — |
| Exchange labels | Dune Spellbook CEX lists (Tron, BTC, Solana, EVM incl. BNB) | — |
| Mixer / bridge labels | curated lists in `labels/seed.py` (Tornado Cash, LI.FI, Wormhole, Polygon PoS, Across, Stargate) + tracker-detected bridges + CoinJoin rule | — |
| LLM (narration only) | Sarvam AI | `SARVAM_API_KEY` |
| Sanctioned addresses + risk category | OFAC SDN official XML (entity + program: CYBER, SDGT/FTO, DPRK, ...) | — |
| VASP registry (FIU-IND, Sahyog status, LE channel) | `backend/data/vasp_registry.json`, every value cited (Lok Sabha Q.5805 annexure, Delhi HC order 29 Apr 2025, exchanges' LE pages) | — |

Known constraint: Etherscan's free tier no longer covers BNB Chain, Base or Optimism, and free BNB RPCs refuse historical log queries, so BNB Chain is the one chain that needs a paid key.

Sourced figures (Oct 2026): 54 VDA SPs registered with FIU-IND as on 9 Mar 2026 (Lok Sabha Unstarred Q.5805, 30 Mar 2026); 33 VDA SPs onboarded on Sahyog per I4C's status report recorded by the Delhi HC on 29 Apr 2025; "45+" exchanges is a media figure (Hindustan Times, 4 Jun 2025), not an official one.

## Core algorithm (reference values)

**Trace limits** (env `TRACE_*`): max depth 5 · fan-out 5 (top by USD) · min $10 · max 2,000 edges · 90-day window · backward depth 2.

**Classification** (first match wins; thresholds in `backend/config/heuristics.yaml`):
1. mixer → terminal stop · 2. bridge → terminal · 3. sanctioned → flag, continue · 4. labelled VASP → terminal
5. **Deposit-sweep:** ≥ 90% of outflow goes to one `vasp_hot`, ≤ 3 outgoing counterparties, first sweep ≤ 24 h after the traced funds arrive → `vasp_deposit` (inferred)
5b. **Exchange cluster:** > 3 counterparties and ≥ 60% of outflow to ONE exchange's labelled wallets → `vasp_hot` (inferred)
6. **Service-like:** ≥ 60 distinct recipients in the latest ≤ 200 transfers, or a full page within 3 days → `unknown_service`
7. known P2P / fintech → `offramp` · 8. else `intermediary`

**Confidence:** `path_factor × (1 − Π(1 − wᵢ·sᵢ))`

| Signal | Weight |
|---|---|
| label tier | 0.9 |
| sweep | 0.7 |
| external tag | 0.5 |
| history (investigation memory) | 0.5 |
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
- **API base:** `/api/v1` — cases, trace jobs, graph, candidates, links, reports, requests and recorded VASP replies, alerts, watch, stats, sahyog webhook stubs (case intake, VASP reply), auth, health. Full list: [architecture.md §6](docs/architecture.md).
- **Roles:** `io` (investigating officer), `analyst` (I4C). VASPs are not users: the VASP side is Sahyog's work.

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

1. Create a case with a real Tron wallet → 2. the graph animates (thickness = value; mixer flagged) → 3. ranked VASP with confidence and reasons → 4. "funds still at deposit" alert → 5. a second case auto-links via a shared deposit address → 6. generate the Section 94 BNSS notice + hashed evidence PDF → send via mock Sahyog → 7. the VASP confirms via Sahyog (reply recorded in BitTrail) → the label becomes verified → confidence rises.

## Status

- [x] Research, PPT (6-slide SIH template), PRD, architecture, schema, phase plan
- [x] Prototype v0.1: phases 1–6 built. Tron / BTC live (ETH / Polygon need `ETHERSCAN_API_KEY`), engine + unit tests, full UI, reports, notices, mock Sahyog + VASP inbox, flywheel, cross-case links, watch poller, Supabase, Dockerfile / Railway config
- [x] Verified: `pytest` (6 pass) and `scripts/smoke_test.py` pass on SQLite and on Supabase; UI walkthrough in Edge with no browser errors
- [x] v0.2: explainable scoring (factor points, why-A-not-B, what-if), history factor, exchange-cluster rule, BNB Chain + Solana adapters, LI.FI bridge continuity, typologies + six-axis risk, timeline + replay, configurable alerts + per-case monitoring, consolidated requests, PDF upgrade (timeline, score calc, patterns, integrity), Sarvam AI (summary, ask, Hindi translation), accuracy test (`docs/eval.md`). 13 tests pass; smoke test passes.
- [x] v0.3 (team asked for everything in the idea deck): keyless Ethereum / Polygon (Blockscout), multi-chain EVM seeds, cross-chain resolution via LI.FI (Tron, BTC, EVM, Solana) + THORChain + deBridge + Wormhole with proactive bridge-vault detection, adaptive dust filter, CoinJoin stop, OFAC risk categories (ransomware / terror financing / DPRK ...), cited VASP routing (Sahyog / LE portal / MLAT) with analyst approval for low-confidence notices, BM25 RAG for "Ask this case" (works without Sarvam), live alerts (SSE), audit viewer + hash-chain verify, GraphML export (NetworkX), chain swimlane graph. 22 tests pass. See docs/architecture.md §13.
- [ ] Not yet: hosted deployment (needs your Railway account), BNB Chain history without a paid key, Docker build tested (Docker isn't installed on the dev machine)

**Demo cases** (`backend/data/demo_cases.json`): real Tron wallets `TKxQN5i…` (Case 1) and `TD1Jp17…` (Case 2) both reach CoinDCX deposit `TADSuFLf…` → linked. Case 3: Tron `TFsmcL9…` → LI.FI (Layerswap) → Ethereum → KuCoin deposit `0xe2097868…` (sweeps into 3 KuCoin hot wallets). Case 4: Bitcoin `bc1qe5w3…` → THORChain (7 swaps) → Ethereum → Bybit deposit `0x911fe8d6…`. Case metadata is fictional.

**Open decisions:** BNB data source (paid Etherscan tier vs another Etherscan-compatible API)? Helius key for faster Solana? Sarvam model choice (`sarvam-105b` vs `sarvam-30b`)?
