from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal, Protocol

Chain = Literal["tron", "ethereum", "polygon", "bsc", "bitcoin", "solana"]
Direction = Literal["out", "in"]
EVM_CHAINS = ("ethereum", "polygon", "bsc")

TRON_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
BTC_RE = re.compile(r"^(bc1[0-9a-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,34})$")
SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class AdapterUnavailable(Exception):
    """Adapter not configured (e.g. missing API key) or data unavailable in demo mode."""


@dataclass
class Transfer:
    chain: str
    tx_hash: str
    log_index: int
    block: int | None
    timestamp: datetime
    from_address: str
    to_address: str
    asset: str
    contract: str | None
    amount_raw: str
    decimals: int
    amount: float
    amount_usd: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class AddressInfo:
    balance_usd: float | None = None
    balances: dict = field(default_factory=dict)
    tx_count: int | None = None


class ChainAdapter(Protocol):
    chain: str

    async def get_transfers(self, address: str, direction: Direction, since: datetime | None,
                            until: datetime | None, limit: int = 200) -> list[Transfer]: ...

    async def get_info(self, address: str) -> AddressInfo: ...

    async def chain_height(self) -> int | None: ...


def detect_chain(address: str) -> str | None:
    a = address.strip()
    if TRON_RE.match(a):
        return "tron"
    if EVM_RE.match(a):
        return "ethereum"
    if BTC_RE.match(a) and len(a) <= 35:
        return "bitcoin"
    if SOL_RE.match(a):
        return "solana"
    return None


def normalize_address(chain: str, address: str) -> str:
    a = address.strip()
    return a.lower() if chain in EVM_CHAINS else a
