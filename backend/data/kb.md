# BitTrail reference notes (retrieval knowledge base)

These notes are retrieved by "Ask this case" next to the case's own evidence. They explain BitTrail's method and the
legal / procedural context in general terms. They are not legal advice; the officer verifies the applicable law.

## Section 94 BNSS: production of documents
Section 94 of the Bharatiya Nagarik Suraksha Sanhita, 2023 lets a court or an officer in charge of a police station
require any person to produce a document, electronic communication or other thing needed for an investigation.
BitTrail drafts disclosure requests to a virtual asset service provider (VASP) under this section: KYC of the account
holder, login / IP logs, and the deposit, trade and withdrawal history of the account linked to the attributed address.

## Section 106 BNSS: seizure / freezing
Section 106 of the BNSS empowers a police officer to seize property suspected to be connected with an offence.
BitTrail's "freeze" and "disclosure + freeze" notices cite Section 94 read with Section 106 and ask the VASP to freeze
the virtual digital assets in the account linked to the deposit address and to confirm the amount frozen.

## Section 63 BSA: electronic evidence certificate
Section 63 of the Bharatiya Sakshya Adhiniyam, 2023 governs admissibility of electronic records and requires a
certificate. BitTrail's evidence PDF ends with a Section 63 certificate template for the officer to complete, and the
report carries a SHA-256 hash of its canonical manifest so any change to the evidence can be detected.

## Sahyog portal
Sahyog is the Indian Cyber Crime Coordination Centre (I4C, Ministry of Home Affairs) portal through which authorised
agencies send notices to intermediaries, including crypto exchanges, for removal of unlawful content and for
information. BitTrail drafts the notice, routes it to the attributed VASP and records the VASP's reply. In this
prototype the Sahyog send and reply are mocked.

## FIU-IND registration of VASPs
Since March 2023 virtual digital asset service providers operating in India are reporting entities under the
Prevention of Money Laundering Act and must register with the Financial Intelligence Unit - India (FIU-IND).
BitTrail's actionability factor is highest for VASPs that are FIU-IND registered and reachable on Sahyog, lower for
foreign VASPs reachable only through a law-enforcement portal, and lowest for unknown entities.

## Routing a request to the right VASP
BitTrail picks the channel from the VASP registry: Sahyog when the VASP is onboarded there; a Section 94 notice to the
nodal officer of an FIU-IND registered VASP; the VASP's own law-enforcement request portal for foreign VASPs that run
one; otherwise the international route (MLAT through MHA, or Interpol through CBI). The chosen channel and why are
shown with every request.

## How confidence is calculated
Confidence = path factor x (1 - product over signals of (1 - weight x signal)). Signals: label tier (0.9), deposit
sweep (0.7), external tag (0.5), investigation memory / history (0.5), share of traced value (0.4), recency (0.2).
Path factor: clean path 1.0; through a bridge 0.5 + 0.5 x continuity; through a mixer 0 (no attribution). Ranking =
value share x confidence x actionability. Each candidate shows the points each factor contributed and what-if changes.

## Deposit-sweep rule (finding the deposit address)
An unlabelled address is inferred to be an exchange deposit address when at least 90% of its outflow goes to one
labelled exchange hot wallet, it has at most 3 outgoing counterparties, and the first sweep happens within 24 hours of
the traced funds arriving. The deposit address identifies one customer account, so it is the key output for a notice.

## Exchange-cluster rule
An unlabelled wallet that sends at least 60% of its outflow to one exchange's labelled wallets while talking to more
counterparties than a deposit address would is inferred to be part of that exchange's wallet cluster (marked inferred).

## Cross-chain tracing and continuity
When funds enter a bridge or cross-chain swap service, or reach a wallet that behaves like one, BitTrail asks public
trackers (LI.FI, THORChain Midgard, deBridge, Wormholescan) where the deposit transaction came out, by its hash. The
trail continues on the destination chain. Continuity score = 0.35 x amount similarity + 0.25 x timing + 0.3 x tracker
confirmation + 0.1 x destination check. If no tracker knows the deposit, an unconfirmed match is tried: the same EVM
address receiving about the same value (less a bridge fee) on another EVM chain within 6 hours.

## Mixers and CoinJoin
BitTrail never attributes through a mixer. Labelled mixers (for example Tornado Cash contracts) and Bitcoin
equal-output CoinJoin transactions (many inputs, at least five identical outputs) stop the trail; the mixer is flagged
in the graph, the typology list and the risk profile.

## Adaptive dust filter
Transfers below max(minimum USD, 0.5% of the value reaching a wallet) are ignored so tiny address-poisoning transfers
and spam do not distract the trace. If the ignored transfers carry at least 20% of a wallet's outflow, they are not dust
but possible structuring: the floor drops back to the minimum and the wallet is flagged.

## Laundering typologies
Splitting: one wallet pays three or more traced recipients within 24 hours. Consolidation: a wallet gathers funds from
two or more traced wallets. Rapid movement: hops made within 60 minutes of the funds arriving. Layering: three or more
intermediary wallets before the exchange. Repeated forwarding: pass-through wallets forwarding at least 90% within 24
hours. Network switching: the trail crosses chains. Mixer use. Sanctions exposure.

## High-risk categories (sanctions programs)
Addresses on the OFAC SDN list carry the program they were designated under. BitTrail translates it: CYBER programs =
cybercrime / ransomware; SDGT and FTO = terrorism financing; DPRK = North Korean state hacking / proliferation
financing; ILLICIT-DRUGS and SDNTK = narcotics; TCO = transnational organised crime; RUSSIA / UKRAINE = sanctions
evasion; IRAN, IFSR, IRGC = Iran sanctions; and named darknet markets such as Hydra Market. Any of these on a trail
raises a high-risk alert.

## Investigation memory and the labels flywheel
Cases are linked when their trails share a suspect, intermediary or deposit address. When a VASP confirms an address
through a Sahyog reply, the address becomes a verified label; every open case that reached it is re-scored and its
confidence rises. A denial becomes a negative label that vetoes the attribution.

## Freeze window
After a trace BitTrail checks the balance of each attributed deposit address. If funds are still there, a
"freeze window" alert asks the officer to send a freeze request immediately; the watch-list keeps polling the suspect,
deposit and end-point wallets and raises alerts on new movement.
