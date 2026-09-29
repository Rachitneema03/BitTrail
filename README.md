# BitTrail

**Automated attribution of unknown crypto wallets to the nearest VASP.**
SIH 2026 · PS 26182 (MHA / I4C) · Team **TrackSense** · prototype v0.1

Paste a suspect wallet from a Sahyog case. BitTrail traces the money across hops on live blockchain data, finds the exchange (VASP) deposit address it landed in, scores how sure it is and whether the VASP can be acted on, seals a court-ready evidence report (SHA-256), and drafts the Section 94 BNSS disclosure / freeze notice.

- **Explainable:** every result lists its reasons and transaction hashes; the LLM never decides attribution (there is no LLM in v0.1).
- **Real data:** Tron (TRX + USDT/USDC), Bitcoin, Ethereum and Polygon (with an Etherscan key).
- **What sets it apart:** deposit-address detection from sweep behaviour, value-weighted ranking, backward on-ramp trace, cross-case linking, a labels flywheel from VASP replies, and freeze-window alerts.

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

On first start the API creates the tables and seeds about 12k public labels plus the VASP registry. It also creates the demo users and two demo cases, and traces them. A committed API snapshot (`backend/data/demo_cache.json.gz`) means the demo traces work even without network or API keys.

Single-server mode: `cd frontend && npm run build`, then only run uvicorn. FastAPI serves the built app at `/`.

### Demo accounts (password `bittrail-demo`, or use the one-click buttons)

| Email | Role |
|---|---|
| `io@bittrail.demo` | Investigating officer |
| `analyst@bittrail.demo` | I4C analyst |
| `coindcx@bittrail.demo` / `binance@bittrail.demo` | Simulated VASP nodal officer (request inbox) |

### Demo flow (about 3 minutes)
1. Dashboard → **Case #1**: the graph shows suspect → intermediary → **CoinDCX deposit address** → CoinDCX hot wallet (live Tron data).
2. The ranked VASP card shows confidence, actionability, reasons (sweep 39 s after arrival) and explorer-linked transactions.
3. **Cross-case link** banner: Case #2 (Delhi) reaches the same deposit address.
4. **Generate evidence report** → Open PDF (manifest hash on every page, BSA §63 certificate template).
5. **Draft Section 94 BNSS notice** → Send via Sahyog (mock).
6. Sign in as **CoinDCX** → Confirm → the label becomes *verified* and both cases' confidence rises (labels flywheel).

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

## Known limits (prototype)
- Sahyog, CFCFRMS and the VASP inbox are **mocked**; FIU-IND / Sahyog status in `backend/data/vasp_registry.json` is hand-curated and must be verified.
- Bitcoin uses a simple largest-output model (no change detection). BNB Chain, Solana and cross-chain bridge decoding are roadmap items.
- Label coverage is public sources only; unknown VASPs appear as "service-like" wallets for manual review.
- Demo case metadata is fictional; wallet addresses are real public on-chain data.
