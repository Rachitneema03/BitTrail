# BitTrail

**Automated attribution of unknown crypto wallets to the nearest VASP.**
SIH 2026 · PS 26182 (MHA / I4C) · Team **TrackSense** · prototype v0.3

Paste a suspect wallet from a Sahyog case. BitTrail traces the money across hops on live blockchain data, finds the exchange (VASP) deposit address it landed in, scores how sure it is and whether the VASP can be acted on, seals a court-ready evidence report (SHA-256), and drafts the Section 94 BNSS disclosure / freeze notice.

- **Explainable:** every result lists its reasons and transaction hashes, a factor-by-factor score breakdown (points that sum to the confidence), "why A, not B?" and what-if scenarios. The LLM never decides attribution.
- **Real data, six chains, no keys needed for five:** Tron (TRX + USDT/USDC), Bitcoin, Solana (SOL/USDT/USDC), Ethereum and Polygon (Blockscout without a key, Etherscan with one), BNB Chain (paid Etherscan tier or `BSC_API_BASE`). An EVM suspect address is traced on every EVM chain where it is active.
- **Cross-chain by default:** when funds enter a bridge or cross-chain swap (or vanish into a wallet that turns out to be one), BitTrail asks LI.FI (incl. Tron and Bitcoin routes), THORChain Midgard, deBridge and Wormholescan where that deposit came out, continues the trace on the destination chain, and scores continuity (amount, timing, tracker confirmation). The graph draws one lane per chain with the bridge hop crossing lanes.
- **Risk and typologies:** adaptive dust filter (address-poisoning aware, structuring guard), CoinJoin detection, OFAC SDN programs translated into ransomware / terror-financing / DPRK / narcotics categories with alerts.
- **Act:** routing per VASP from cited sources (Sahyog / LE portal / MLAT), analyst approval for low-confidence notices, live alerts (server-sent events), hash-chained audit log with one-click verification, GraphML export of the trace graph.
- **What sets it apart:** deposit-address and exchange-cluster detection from behaviour, value-weighted ranking, two-way trace (off-ramp + on-ramp), investigation memory (cross-case links + history factor + labels flywheel from VASP replies), laundering typologies and a six-axis risk profile, investigation replay and timeline, freeze-window and configurable alerts, consolidated Sahyog requests.
- **Sarvam AI (optional):** plain-language case summary (English / Hindi), "Ask this case" (BM25 retrieval over the case's evidence + legal / method notes, answers cite passages), and Hindi translation of notices, all written only from the computed evidence. Without `SARVAM_API_KEY` a template summary is shown and "Ask" returns the retrieved evidence itself.

Specs: [CONTEXT.md](CONTEXT.md) · [docs/prd.md](docs/prd.md) · [docs/architecture.md](docs/architecture.md) · [docs/schema.md](docs/schema.md) · [docs/phases.md](docs/phases.md)

## Run locally

Requirements: Python 3.12, Node 20+.

```bash
# 1. backend
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
cp ../.env.example ../.env      # then edit: DATABASE_URL (omit for SQLite), JWT_SECRET, optional API keys
uvicorn app.main:app --reload   # http://localhost:8000/docs

# 2. frontend (second terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173 (proxies /api to :8000)
```

On first start the API creates the tables and seeds about 17k public labels (7k unique addresses) plus the VASP registry. It also creates the demo users and two demo cases, and traces them. A committed API snapshot (`backend/data/demo_cache.json.gz`) means the demo traces work even without network or API keys.

Single-server mode: `cd frontend && npm run build`, then only run uvicorn. FastAPI serves the built app at `/`.

### Demo accounts (password `bittrail-demo`, or use the one-click buttons)

| Email | Role |
|---|---|
| `io@bittrail.demo` | Investigating officer |
| `analyst@bittrail.demo` | I4C analyst |

VASPs are not BitTrail users: they receive notices and reply on Sahyog.

### Demo flow (about 3 minutes)
1. Dashboard → **Case #1**: the graph shows suspect → intermediary → **CoinDCX deposit address** → CoinDCX hot wallet (live Tron data).
2. The ranked VASP card shows confidence, actionability, reasons (sweep 39 s after arrival) and explorer-linked transactions.
3. **Cross-case link** banner: Case #2 (Delhi) reaches the same deposit address.
4. **Generate evidence report** → Open PDF (manifest hash on every page, BSA §63 certificate template).
5. **Draft Section 94 BNSS notice** → Send via Sahyog (mock).
6. **Sahyog requests** → **Record VASP reply** → Confirmed (CoinDCX's reply received via Sahyog) → the label becomes *verified* and both cases' confidence rises (labels flywheel). Sahyog can also push the reply: `POST /api/v1/sahyog/reply` (mock webhook, matched by Sahyog ref).
7. **Cross-chain:** Case #3 (Tron USDT → LI.FI / Layerswap → Ethereum → KuCoin deposit) and Case #4 (Bitcoin → THORChain → Ethereum → Bybit deposit). The graph shows a TRON / BITCOIN lane and an ETHEREUM lane with the bridge hop crossing them; the cross-chain card shows both transactions and the continuity breakdown; the notice names the cross-chain path.

## Deploy (Railway + Supabase)

1. Push this folder to a GitHub repo (`.env` is git-ignored).
2. Railway → New project → Deploy from GitHub. It builds the root `Dockerfile` (React build + FastAPI) using `railway.json`.
3. Service → Variables:
   - `DATABASE_URL`: Supabase → Connect → **Session pooler** URI (IPv4). URL-encode `@` in the password as `%40`.
   - `JWT_SECRET`: a long random string.
   - optional: `TRONGRID_API_KEY`, `ETHERSCAN_API_KEY`, `DEMO_MODE=true` (offline demo from the snapshot).
4. Generate a domain. The health check is `/api/v1/health`.

Alternatives: `docker compose up --build` (app + local Postgres), or Render / Fly.io with the same Dockerfile.

## Useful scripts (run from `backend/`)

| Command | What it does |
|---|---|
| `python -m pytest -q` | Engine unit tests (synthetic graph, no network) |
| `python scripts/smoke_test.py http://localhost:8000` | End-to-end API check of the full demo flow |
| `python scripts/trace_cli.py tron T… --since 2026-09-10T00:00:00Z` | Trace from the terminal |
| `python scripts/fetch_label_sources.py` | Refresh label seeds (Dune Spellbook CEX lists, OFAC SDN) |
| `python scripts/export_demo_cache.py` | Snapshot cached API responses for offline demos |
| `python scripts/eval_hide_and_seek.py 5` | Accuracy test on live Tron data (label ablation) → `docs/eval.md` |
| `python scripts/benchmark.py` | Trace-time benchmark of the demo cases, cold + warm, plus a depth sweep → `docs/benchmark.md` / `.json` (use a fresh `DATABASE_URL` for true cold numbers) |

## Known limits (prototype)
- Sahyog (sending notices, VASP replies) and CFCFRMS are **mocked**. FIU-IND / Sahyog status and LE channels in `backend/data/vasp_registry.json` cite public sources (Lok Sabha Q.5805 annexure, Delhi HC order of 29 Apr 2025, exchanges' pages); nodal contacts are placeholders. Verify before operational use.
- Bitcoin outflows are all outputs except change back to the same address (no change detection). Solana on the public RPC is slow (rate limits); use a Helius RPC URL. BNB Chain needs a paid Etherscan tier or `BSC_API_BASE`. Cross-chain continuation needs a public tracker to know the deposit (LI.FI, THORChain, deBridge, Wormhole); other bridges and instant exchangers stop the trail with a flag (same-address fallback only for labelled bridges).
- Label coverage is public sources only; unknown VASPs appear as "service-like" wallets for manual review.
- Demo case metadata is fictional; wallet addresses are real public on-chain data.
