# BitTrail trace-time benchmark

Run 2026-10-06 15:16 UTC on live public APIs, free tiers, no API keys (TronGrid, mempool.space / blockstream.info, Blockscout v2, Solana public RPC, LI.FI / THORChain / deBridge / Wormholescan). Cold = empty API cache; warm = the same trace again (every response cached, as for re-traces and DEMO_MODE).

**Median: 26.3 s cold, 0.1 s warm. Slowest cold trace: 118.9 s.**

| Case | Chains | Addresses | Cross-chain hops | Nearest VASP | Cold (s) | Warm (s) |
| --- | --- | --- | --- | --- | --- | --- |
| Fake trading app: USDT investment scam (demo) | tron | 6 | 0 | CoinDCX (0.96) | 42.1 | 0.1 |
| Task-based part-time job scam (demo) | tron | 5 | 0 | CoinDCX (0.96) | 10.5 | 0.0 |
| Fake crypto trading app: USDT bridged Tron to Ethereum (demo) | tron -> ethereum | 10 | 1 | KuCoin (0.96) | 8.8 | 0.1 |
| Digital arrest scam: Bitcoin swapped to Ethereum via THORChain (demo) | bitcoin -> ethereum | 44 | 7 | Bybit (0.94) | 118.9 | 0.7 |

## Depth sweep (Digital arrest scam: Bitcoin swapped to Ethereum via THORChain (demo), warm cache)

Fan-out 5 bounds one chain's forward trace at 1 + 5 + 25 + ... addresses per seed; real trails stay far below it because most wallets pay fewer than five recipients and exchanges, bridges and mixers end a branch. Bridge destinations (a new chain) and exchange hot wallets reached by a sweep add addresses on top; the 2,000-link cap bounds the total. 'All addresses' also includes the 2-hop backward (on-ramp) trace.

| Depth | Forward addresses | All addresses | Links | Fan-out bound (one chain) | Seconds (warm) |
| --- | --- | --- | --- | --- | --- |
| 1 | 7 | 13 | 14 | 6 | 1.1 |
| 2 | 12 | 18 | 20 | 31 | 0.1 |
| 3 | 21 | 27 | 31 | 156 | 0.2 |
| 4 | 27 | 33 | 43 | 781 | 0.7 |
| 5 | 38 | 44 | 55 | 3906 | 0.7 |
