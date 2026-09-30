from .base import (EVM_CHAINS, AdapterUnavailable, AddressInfo, ChainAdapter, Transfer, detect_chain,
                   normalize_address)
from .btc import BtcAdapter
from .evm import EvmAdapter
from .solana import SolanaAdapter
from .tron import TronAdapter

CHAINS = ("tron", "ethereum", "polygon", "bsc", "bitcoin", "solana")
PROVIDERS = {"tron": "TronGrid (api.trongrid.io)", "ethereum": "Etherscan API V2 (chainid 1)",
             "polygon": "Etherscan API V2 (chainid 137)", "bsc": "Etherscan API V2 (chainid 56) / BSC_API_BASE",
             "bitcoin": "mempool.space", "solana": "Solana JSON-RPC"}
_ADAPTERS: dict[str, ChainAdapter] = {}


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
           "get_adapter", "CHAINS", "PROVIDERS", "EVM_CHAINS"]
