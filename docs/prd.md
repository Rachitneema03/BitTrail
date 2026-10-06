# BitTrail — Product Requirements (PRD)

**Problem statement:** SIH 2026 · PS 26182 — Automated Attribution of Unknown Cryptocurrency Wallets to Nearest VASPs through Blockchain Intelligence APIs (MHA / I4C)
**Status:** Draft v0.1 · MVP prototype scope
**One line:** Paste a suspect wallet from a Sahyog case → get the nearest exchange (VASP) that can freeze the funds, with confidence, evidence, and a drafted lawful request.

---

## 1. Problem

- Investment and other cyber-fraud proceeds are increasingly moved as crypto, especially **USDT on Tron**. India lost **₹22,845.73 Cr** to cyber fraud in 2024 (MHA, Lok Sabha Q.344, 22 Jul 2025).
- Suspect wallets are usually **unhosted**, so there is no one to ask who owns them. The funds eventually pass through a **VASP** (exchange, custodial wallet, P2P platform) that holds KYC.
- Police can send disclosure and freeze requests through **Sahyog** (33 VDA service providers onboarded per I4C's status report to the Delhi High Court, Apr 2025; "45+" per media reports, Jun 2025), but they **don't know which VASP** to send them to.
- Finding that VASP means manually tracing hop by hop across chains, through mixers and bridges. That needs scarce experts, and meanwhile the funds cash out.
- Real cases also show the reverse pattern: mules **buy USDT on an exchange's P2P market** (the on-ramp), and trails that **end in private wallets** abroad (e.g. ED's ₹303 Cr case, Jul 2026).

## 2. Users

| Persona | Needs |
|---|---|
| **Investigating Officer (IO)**, state cyber cell | Paste a wallet, get "which exchange, how sure, what to send" without blockchain expertise |
| **I4C / Sahyog analyst** | See cases linked across states, prioritise freezes, track requests |
| **VASP nodal officer** (via Sahyog, not a BitTrail user) | Receive precise requests with transaction-level evidence on Sahyog; confirm or deny there |
| **Supervisor / prosecutor** (read-only) | A court-ready report with reproducible evidence |

## 3. Goals and non-goals

**Goals (MVP)**
1. Automatically trace suspect wallets on **Tron (TRX + USDT-TRC20), Ethereum, Polygon, Bitcoin**.
2. Identify and rank the **nearest VASP by value reached**, with an explainable confidence score.
3. Tag each wallet type: exchange hot wallet, deposit address, mixer, bridge, sanctioned, P2P/fintech off-ramp, unknown service.
4. Generate a **hash-sealed evidence report** and a **drafted Section 94 BNSS notice** routed through a mock Sahyog.
5. **Link cases** that share deposit addresses, and **alert** when watched funds move.
6. Deploy at a public demo URL on real blockchain data.

**Non-goals (MVP)**
- Real integration with Sahyog, CFCFRMS or Samanvaya (mocked; interfaces designed).
- Solana, BNB Chain, and cross-chain bridge decoding (adapters planned, not built).
- A graph neural network in production (an offline experiment at most).
- On-prem LLM, multi-tenant auth, horizontal scaling.
- Probabilistically following funds through a mixer.

## 4. Success metrics

| Metric | Target (MVP) | How measured |
|---|---|---|
| Time from wallet to ranked VASP (warm cache) | **< 60 s** | Timer in the UI and job logs |
| Precision@1 for VASP attribution | Report the measured value; target ≥ 0.7 | Hide-and-seek test on held-out labelled deposit addresses |
| Demo cases reaching a labelled VASP | ≥ 3 of 5 | Pre-verified demo set |
| Evidence integrity | 100% of reports reproduce their hash | Recompute SHA-256 over the manifest |
| Every result explainable | 100% of candidates list reasons + transaction hashes | UI check |

## 5. User stories

- **US-1** As an IO, I create a case with FIR no., NCRP ID, fraud date, amount, and 1+ wallet addresses, so the system can trace them.
- **US-2** As an IO, I see a live graph of how the money moved, with thickness showing value, so I understand the trail.
- **US-3** As an IO, I get a ranked list of candidate VASPs, each with the deposit address, hops, share of value, confidence, reasons and "funds still there?", so I know where to send a request.
- **US-4** As an IO, I see where the suspect's funds **came from** (the on-ramp exchange), so I can also pursue the buyer's KYC.
- **US-5** As an IO, I see mixers, bridges and sanctioned wallets flagged, and the trace stops honestly at mixers.
- **US-6** As an IO, I download an evidence PDF with every transaction and a SHA-256 manifest hash.
- **US-7** As an IO, I generate a pre-filled disclosure or freeze notice for the chosen VASP and "send" it through Sahyog.
- **US-8** As an I4C analyst, I'm told when a new case shares a deposit address with an existing case.
- **US-9** As an IO, I'm alerted when funds on a watched path move, especially into an exchange.
- **US-10** When a VASP confirms or denies ownership of a deposit address on Sahyog, the reply is recorded in BitTrail (by the officer, or pushed by Sahyog) and the system learns from it (the labels flywheel).
- **US-11** As an analyst, I see a dashboard: cases, value traced, top VASPs, open requests, alerts.

## 6. Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-1 | Case CRUD with wallets; auto-detect the chain from the address format | P0 |
| FR-2 | Chain adapters (Tron, EVM [ETH, Polygon], BTC) returning a common `Transfer` record | P0 |
| FR-3 | Cache every external API response; demo-mode serves from the cache only | P0 |
| FR-4 | Forward trace: breadth-first search with depth, fan-out, dust and time-window limits; tracks how the stolen value splits | P0 |
| FR-5 | Backward trace: 2 hops to find the on-ramp | P1 |
| FR-6 | Label lookup from curated sources + the VASP registry | P0 |
| FR-7 | Rule that detects deposit addresses from how they sweep funds | P0 |
| FR-8 | Mixer / bridge / sanctioned hard stop and flag | P0 |
| FR-9 | Confidence (noisy-OR) + actionability + ranking | P0 |
| FR-10 | Graph view (Cytoscape) + Sankey + timeline | P0 / P1 |
| FR-11 | Evidence report (HTML + PDF) + SHA-256 manifest | P0 |
| FR-12 | Section 94 BNSS notice draft + mock Sahyog routing + VASP reply screen | P0 |
| FR-13 | Labels flywheel: a VASP confirmation creates a verified label and re-scores open cases | P1 |
| FR-14 | Cross-case linking on deposit and hot-wallet addresses | P1 |
| FR-15 | Watch-list poller + alerts | P1 |
| FR-16 | Dashboard statistics | P2 |
| FR-17 | LLM case narrative (template fallback) | P2 |
| FR-18 | Append-only audit log of every action | P1 |

## 7. Non-functional requirements

- **Explainability:** no attribution without listed evidence; the LLM never decides attribution.
- **Reproducibility:** every trace records the block height or time it ran at and caches all inputs, so it can be re-run.
- **Performance:** limits of max depth 5, fan-out 5, 2,000 edges per trace.
- **Security (prototype):** simple role login (IO / analyst / VASP), secrets in environment variables, no personal data beyond mock case metadata.
- **Resilience:** demo mode works offline from the cache; a Docker Compose fallback for local runs.
- **Cost:** only free or low-cost API tiers.

## 8. Acceptance criteria (the demo)

1. Create a case with a real Tron wallet → trace finishes in under 60 s → graph renders.
2. The top candidate is a labelled exchange deposit address, shown with reasons and transaction hashes.
3. A mixer branch is shown flagged and stopped.
4. A second case sharing the deposit address shows a "Linked to Case #…" banner.
5. The PDF downloads; its manifest hash matches the hash shown.
6. Notice generated → sent via mock Sahyog → VASP confirms on Sahyog, reply recorded in BitTrail → label becomes "verified" and confidence rises.
7. A watch-list alert fires (simulated or real) for movement on the path.

## 9. Assumptions

- Public label sources plus exchange proof-of-reserves lists cover the major hot wallets of Binance, OKX, Bybit, KuCoin, etc.
- USDT is valued at $1. Other assets are valued with a daily price from a free price API.
- The FIU-IND registration and Sahyog onboarding status of each VASP is curated by hand in `vasp_registry.json`.

## 10. Open questions (for the team)

- Include BNB Chain (paid Etherscan tier, or BSCTrace free tier) in the MVP?
- Offer an LLM narrative at all, or template text only?
- Is the demo login-gated, or open with a read-only demo user?
- Who owns the recorded video and the deck screenshots?
