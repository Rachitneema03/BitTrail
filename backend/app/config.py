from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore")

    database_url: str = f"sqlite:///{BACKEND_DIR / 'bittrail.db'}"
    jwt_secret: str = "change-me-in-production"
    demo_mode: bool = False  # serve blockchain data from cache only

    trongrid_api_key: str = ""
    etherscan_api_key: str = ""
    etherscan_bsc: bool = False   # the Etherscan key is a paid tier that covers BNB Chain (chainid 56)
    bsc_api_base: str = ""        # optional Etherscan-compatible BNB Chain API (Etherscan's free tier excludes BNB)
    bsc_api_key: str = ""
    blockscout_fallback: bool = True  # Ethereum / Polygon via the keyless Blockscout API when no Etherscan key
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"  # or a Helius / QuickNode RPC URL
    bridge_tracker: bool = True   # resolve cross-chain destinations via public bridge / swap trackers
    crosschain_providers: str = "lifi,thorchain,debridge,wormhole"
    thorchain_midgard_url: str = "https://gateway.liquify.com/chain/thorchain_midgard/v2"
    neo4j_uri: str = ""           # optional: mirror every trace graph into Neo4j (bolt://...)
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # Sarvam AI (optional): narrates evidence, answers questions, translates. Never used for attribution.
    sarvam_api_key: str = ""
    sarvam_model: str = "sarvam-105b"
    sarvam_base: str = "https://api.sarvam.ai"

    app_version: str = "0.3.0"

    trace_max_depth: int = 5
    trace_fanout: int = 5
    trace_min_usd: float = 10.0
    trace_max_edges: int = 2000
    trace_window_days: int = 90
    trace_back_depth: int = 2

    watch_interval_seconds: int = 120
    cors_origins: str = "*"
    frontend_dist: str = str(ROOT_DIR / "frontend" / "dist")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def settings() -> Settings:
    s = Settings()
    # Railway / Heroku style URLs -> SQLAlchemy psycopg3 driver
    if s.database_url.startswith("postgres://"):
        s.database_url = "postgresql+psycopg://" + s.database_url[len("postgres://"):]
    elif s.database_url.startswith("postgresql://"):
        s.database_url = "postgresql+psycopg://" + s.database_url[len("postgresql://"):]
    return s


@lru_cache
def heuristics() -> dict:
    with open(BACKEND_DIR / "config" / "heuristics.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
