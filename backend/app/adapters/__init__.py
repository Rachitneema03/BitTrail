from .base import AdapterUnavailable, AddressInfo, ChainAdapter, Transfer, detect_chain, normalize_address
from .btc import BtcAdapter
from .evm import EvmAdapter
from .tron import TronAdapter

_ADAPTERS: dict[str, ChainAdapter] = {}


def get_adapter(chain: str) -> ChainAdapter:
    if chain not in _ADAPTERS:
        if chain == "tron":
            _ADAPTERS[chain] = TronAdapter()
        elif chain in ("ethereum", "polygon"):
            _ADAPTERS[chain] = EvmAdapter(chain)
        elif chain == "bitcoin":
            _ADAPTERS[chain] = BtcAdapter()
        else:
            raise AdapterUnavailable(f"unsupported chain: {chain}")
    return _ADAPTERS[chain]


__all__ = ["AdapterUnavailable", "AddressInfo", "ChainAdapter", "Transfer", "detect_chain",
           "normalize_address", "get_adapter"]
