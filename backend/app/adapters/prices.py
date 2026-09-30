"""Daily USD prices (close) for native assets, via Binance public klines. Stablecoins = 1.0."""
from __future__ import annotations

from datetime import datetime, timezone

from ..db import SessionLocal
from ..models import Price
from .base import AdapterUnavailable
from .http import cached_get

STABLES = {"USDT", "USDC", "USDC.E"}
SYMBOLS = {"TRX": "TRXUSDT", "ETH": "ETHUSDT", "BTC": "BTCUSDT", "POL": "POLUSDT", "MATIC": "MATICUSDT",
           "BNB": "BNBUSDT", "SOL": "SOLUSDT"}
# used only if the price API is unreachable and nothing is cached; flagged as approximate in stats
FALLBACK = {"TRX": 0.3, "ETH": 3000.0, "BTC": 100000.0, "POL": 0.3, "MATIC": 0.3, "BNB": 600.0, "SOL": 150.0}

_mem: dict[tuple[str, str], float] = {}


async def usd_price(asset: str, ts: datetime) -> float:
    asset = asset.upper()
    if asset in STABLES:
        return 1.0
    day = ts.astimezone(timezone.utc).strftime("%Y-%m-%d")
    k = (asset, day)
    if k in _mem:
        return _mem[k]
    with SessionLocal() as db:
        row = db.get(Price, {"asset": asset, "day": day})
        if row:
            _mem[k] = row.usd
            return row.usd
    symbol = SYMBOLS.get(asset)
    price = None
    if symbol:
        start = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        is_today = day == datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            data = await cached_get("binance", "https://api.binance.com/api/v3/klines",
                                    {"symbol": symbol, "interval": "1d", "startTime": start, "limit": 1},
                                    ttl_seconds=3600 if is_today else None)
            if data:
                price = float(data[0][4])
        except AdapterUnavailable:
            price = None
    if price is None:
        price = FALLBACK.get(asset, 0.0)
    else:
        with SessionLocal() as db:
            if not db.get(Price, {"asset": asset, "day": day}):
                db.add(Price(asset=asset, day=day, usd=price))
                db.commit()
    _mem[k] = price
    return price
