# BitTrail accuracy test (hide-and-seek, label ablation)

Run: 2026-09-29 20:39 UTC · live Tron data · 6 ground-truth deposit addresses sweeping into 3 labelled hot wallets (Binance, CoinDCX).

Ground truth = senders whose outflow goes at least 90% to one labelled exchange hot wallet (deposit-sweep definition, all labels known). Test (b) hides that hot wallet's label and checks whether BitTrail still names the right exchange through other labels and the exchange-cluster rule.

| Condition | Precision@1 (right exchange ranked first) | Named any exchange | Named or flagged an unlabelled service | Mean confidence |
| --- | --- | --- | --- | --- |
| baseline (all labels) | 100% (6/6) | 100% | 100% | 0.87 |
| hot-wallet label hidden | 0% (0/6) | 0% | 33% | 0.00 |

Reading: with the exchange's labels known, BitTrail ranked the correct exchange first in 6 of 6 cases. With the receiving hot wallet's label removed it named an exchange in 0% of cases and named or flagged the unlabelled wallet for review in 33%. Exchange hot wallets transact almost only with unlabelled addresses, so label coverage is the bottleneck: the VASP-reply labels flywheel and more label sources address it.

Small sample on live data: treat as indicative, not a benchmark. Re-run with a larger `per_hot_wallet` for a stronger estimate.
