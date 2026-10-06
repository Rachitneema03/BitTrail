from ..config import settings
from .base import (EVM_CHAINS, AdapterUnavailable, AddressInfo, ChainAdapter, Transfer, detect_chain,
                   normalize_address)
from .btc import BtcAdapter
from .evm import EvmAdapter, provider_for, provider_name
from .solana import SolanaAdapter
from .tron import TronAdapter

CHAINS = ("tron", "ethereum", "polygon", "bsc", "bitcoin", "solana")
_ADAPTERS: dict[str, ChainAdapter] = {}


def provider_label(chain: str) -> str:
    """Human-readable data source actually used for a chain (recorded in evidence integrity)."""
    if chain in EVM_CHAINS:
        return provider_name(chain)
    if chain == "solana":
        url = settings().solana_rpc_url
        return "Solana JSON-RPC (Helius)" if "helius" in url else "Solana JSON-RPC (public)"
    return {"tron": "TronGrid (api.trongrid.io)", "bitcoin": "mempool.space"}.get(chain, chain)


def chain_status() -> dict[str, dict]:
    """Which chains can be traced right now, through which source, and whether a key is needed."""
    s = settings()
    out = {}
    for c in CHAINS:
        live = (provider_for(c) is not None) if c in EVM_CHAINS else True
        out[c] = {"live": live or s.demo_mode, "source": provider_label(c),
                  "keyless": c not in EVM_CHAINS or (provider_for(c) or ("", "", ""))[2] == "blockscout"}
    return out


def get_adapter(chain: str) -> ChainAdapter:
    if chain not in _ADAPTERS:
        if chain == "tron":
            _ADAPTERS[chain] = TronAdapter()
        elif chain in EVM_CHAINS:
            _ADAPTERS[chain] = EvmAdapter(chain)
        elif chain == "bitcoin":
            _ADAPTERS[chain] = BtcAdapter()
        elif chain == "solana":
            _ADAPTERS[chain] = SolanaAdapter()
        else:
            raise AdapterUnavailable(f"unsupported chain: {chain}")
    return _ADAPTERS[chain]


__all__ = ["AdapterUnavailable", "AddressInfo", "ChainAdapter", "Transfer", "detect_chain", "normalize_address",
           "get_adapter", "CHAINS", "EVM_CHAINS", "provider_label", "chain_status"]
