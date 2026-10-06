from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraceParams:
    max_depth: int = 5
    fanout: int = 5
    min_usd: float = 10.0
    max_edges: int = 2000
    window_days: int = 90
    back_depth: int = 2


@dataclass
class Node:
    chain: str
    address: str
    depth: int
    kind: str = "intermediary"
    value_share: float = 0.0
    value_usd: float = 0.0
    entity: str | None = None
    label_source: str | None = None
    label_tier: str | None = None
    flags: set[str] = field(default_factory=set)
    reasons: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    terminal: bool = False
    arrival: datetime | None = None
    parent: str | None = None
    parent_share: float = 0.0
    parent_txs: list[str] = field(default_factory=list)
    sweep_to: str | None = None
    sweep_share: float | None = None

    @property
    def id(self) -> str:
        return f"{self.chain}:{self.address}"


@dataclass
class Edge:
    chain: str
    frm: str
    to: str
    direction: str  # forward | backward | sweep | bridge | mix
    assets: set[str] = field(default_factory=set)
    amount_usd: float = 0.0
    value_share: float = 0.0
    tx_hashes: list[str] = field(default_factory=list)
    tx_count: int = 0
    first_ts: datetime | None = None
    block: int | None = None
    to_chain: str | None = None  # set on cross-chain (bridge) edges

    @property
    def dest_chain(self) -> str:
        return self.to_chain or self.chain


@dataclass
class TraceResult:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], Edge] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    seed_out_usd: float = 0.0
    crosschain: list[dict] = field(default_factory=list)  # every resolved bridge / swap hop, with continuity
    dust: dict = field(default_factory=lambda: {"transfers": 0, "usd": 0.0, "poisoning": 0})

    def node(self, chain: str, address: str, depth: int) -> tuple[Node, bool]:
        key = f"{chain}:{address}"
        if key in self.nodes:
            n = self.nodes[key]
            if depth >= 0 and 0 <= n.depth and depth < n.depth:
                n.depth = depth
            return n, False
        n = Node(chain=chain, address=address, depth=depth)
        self.nodes[key] = n
        return n, True

    def edge(self, chain: str, frm: str, to: str, direction: str) -> Edge:
        k = (f"{chain}:{frm}", f"{chain}:{to}", direction)
        if k not in self.edges:
            self.edges[k] = Edge(chain=chain, frm=frm, to=to, direction=direction)
        return self.edges[k]

    def xedge(self, from_chain: str, frm: str, to_chain: str, to: str, direction: str) -> Edge:
        k = (f"{from_chain}:{frm}", f"{to_chain}:{to}", direction)
        if k not in self.edges:
            self.edges[k] = Edge(chain=from_chain, frm=frm, to=to, direction=direction, to_chain=to_chain)
        return self.edges[k]


@dataclass
class CandidateDraft:
    vasp_name: str
    role: str
    chain: str
    address: str
    address_kind: str
    hops: int
    value_share: float
    value_usd: float
    confidence: float
    actionability: float
    rank_score: float
    signals: dict
    reasons: list[str]
    evidence_tx: list[str]
    path: list[str]
    funds_status: str = "unknown"
    explain: dict = field(default_factory=dict)
