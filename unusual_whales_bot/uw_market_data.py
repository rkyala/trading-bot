"""
Real Market Data Provider (BLOCKER FIX #2, #7)

Supplies the OHLCV/price methods the rest of the bot expected but that did not
exist anywhere in the codebase:
  - get_historical_candles()  <- Technical Gates 9/10 called this; it was missing
  - get_intraday_ticks()      <- Technical Gate 11 (VWAP) called this; it was missing
  - get_underlying_price()    <- replaces the hardcoded `current_price = 4500`
  - get_atr()                 <- replaces the 3-symbol hardcoded ATR lookup table

Backed by yfinance with retry/backoff and short-lived caching so a 5-minute
cycle over ~20 symbols does not hammer the upstream.

Prices are the foundation of every stop, target and P&L number in this bot.
If a price cannot be sourced, these methods return None and callers MUST skip
the trade rather than substitute a placeholder.
"""

import logging
import time
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:  # pragma: no cover
    YFINANCE_AVAILABLE = False
    logger.error("❌ yfinance not installed - market data unavailable")


# Index/underlying symbols that UW reports but yfinance spells differently.
SYMBOL_MAP = {
    "SPX": "^GSPC",
    "SPXW": "^GSPC",
    "NDX": "^NDX",
    "NDXP": "^NDX",
    "RUT": "^RUT",
    "VIX": "^VIX",
}

# Symbols with no tradeable underlying we can price/execute against.
UNTRADEABLE = {"SPX", "SPXW", "NDX", "NDXP", "RUT", "VIX"}


class MarketDataProvider:
    """Real OHLCV + price data with caching and retry."""

    def __init__(self, cache_ttl_seconds: int = 60):
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Any] = {}
        self._cache_time: Dict[str, float] = {}
        self._lock = threading.Lock()
        self.stats = {"hits": 0, "misses": 0, "failures": 0}

    # ------------------------------------------------------------------ utils

    def _resolve(self, symbol: str) -> str:
        return SYMBOL_MAP.get(symbol.upper(), symbol.upper())

    def _cache_get(self, key: str):
        with self._lock:
            if key in self._cache:
                if time.time() - self._cache_time.get(key, 0) < self.cache_ttl:
                    self.stats["hits"] += 1
                    return self._cache[key]
                self._cache.pop(key, None)
                self._cache_time.pop(key, None)
        self.stats["misses"] += 1
        return None

    def _cache_put(self, key: str, value):
        with self._lock:
            self._cache[key] = value
            self._cache_time[key] = time.time()

    def _fetch_history(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        """Fetch OHLCV with exponential backoff (1s/2s/4s)."""
        if not YFINANCE_AVAILABLE:
            return None

        ticker = self._resolve(symbol)
        key = f"hist:{ticker}:{period}:{interval}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        for attempt in range(3):
            try:
                df = yf.Ticker(ticker).history(
                    period=period, interval=interval, auto_adjust=False
                )
                if df is not None and not df.empty:
                    df = df.dropna(subset=["Close"])
                    if not df.empty:
                        self._cache_put(key, df)
                        return df
                logger.debug(f"Empty history for {ticker} ({period}/{interval})")
            except Exception as e:
                logger.debug(f"yfinance attempt {attempt + 1} failed for {ticker}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

        self.stats["failures"] += 1
        logger.warning(f"⚠️ Could not fetch history for {symbol} ({period}/{interval})")
        return None

    # ------------------------------------------------------------------- API

    def get_underlying_price(self, symbol: str) -> Optional[float]:
        """
        Current underlying price. Returns None when unavailable — callers must
        skip the trade rather than fall back to a placeholder.
        """
        df = self._fetch_history(symbol, period="1d", interval="1m")
        if df is None or df.empty:
            df = self._fetch_history(symbol, period="5d", interval="1d")
        if df is None or df.empty:
            return None
        try:
            price = float(df["Close"].iloc[-1])
            return price if price > 0 and np.isfinite(price) else None
        except Exception:
            return None

    def get_historical_candles(
        self, symbol: str, interval: str = "day", limit: int = 30
    ) -> List[Dict]:
        """
        Daily OHLCV candles. Signature matches what TechnicalGates expects
        (it was calling this method on a client that never defined it).
        """
        yf_interval = {"day": "1d", "1d": "1d", "hour": "1h", "1h": "1h"}.get(interval, "1d")
        period = "3mo" if yf_interval == "1d" else "1mo"

        df = self._fetch_history(symbol, period=period, interval=yf_interval)
        if df is None or df.empty:
            return []

        df = df.tail(limit)
        return [
            {
                "date": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            }
            for idx, row in df.iterrows()
            if np.isfinite(row["Close"]) and row["Close"] > 0
        ]

    def get_intraday_ticks(self, symbol: str, interval: str = "5m") -> List[Dict]:
        """Intraday bars for the current session (used for VWAP, Gate 11)."""
        df = self._fetch_history(symbol, period="1d", interval=interval)
        if df is None or df.empty:
            return []

        return [
            {
                "time": idx.isoformat(),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row.get("Volume", 0) or 0),
            }
            for idx, row in df.iterrows()
            if np.isfinite(row["Close"]) and row["Close"] > 0
        ]

    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """
        True 14-period ATR from real candles (replaces the hardcoded
        {"SPX": 18.0, "NDX": 40.0, "RUT": 25.0} lookup that returned 18.0
        for every equity symbol).
        """
        candles = self.get_historical_candles(symbol, interval="day", limit=period + 15)
        if len(candles) < period + 1:
            return None

        df = pd.DataFrame(candles)
        prev_close = df["close"].shift(1)
        true_range = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = true_range.rolling(window=period).mean().iloc[-1]
        if pd.isna(atr) or atr <= 0:
            return None
        return float(atr)

    def is_tradeable(self, symbol: str) -> bool:
        """Cash-settled index products have no underlying share to trade."""
        return symbol.upper() not in UNTRADEABLE

    def log_stats(self):
        logger.info(
            f"📊 MarketData cache: {self.stats['hits']} hits, "
            f"{self.stats['misses']} misses, {self.stats['failures']} failures"
        )


class AsyncMarketDataAdapter:
    """
    Async-shaped view over MarketDataProvider.

    TechnicalGates awaits `get_historical_candles()` / `get_intraday_ticks()`.
    yfinance is blocking, so the calls are dispatched to a thread to avoid
    stalling the event loop (a 20-symbol cycle would otherwise block the
    risk-monitoring loop for seconds at a time).
    """

    def __init__(self, provider: "MarketDataProvider"):
        self._p = provider

    async def get_historical_candles(
        self, symbol: str, interval: str = "day", limit: int = 30
    ) -> List[Dict]:
        import asyncio
        return await asyncio.to_thread(
            self._p.get_historical_candles, symbol, interval, limit
        )

    async def get_intraday_ticks(self, symbol: str, interval: str = "5m") -> List[Dict]:
        import asyncio
        return await asyncio.to_thread(self._p.get_intraday_ticks, symbol, interval)

    async def get_underlying_price(self, symbol: str) -> Optional[float]:
        import asyncio
        return await asyncio.to_thread(self._p.get_underlying_price, symbol)

    def __getattr__(self, name):
        # Fall through to the sync provider for everything else (get_atr, etc.)
        return getattr(self._p, name)


# Shared singleton — cache is only useful if callers share it.
_provider: Optional[MarketDataProvider] = None
_async_adapter: Optional[AsyncMarketDataAdapter] = None


def get_market_data():
    """
    Price provider, selected by PRICE_SOURCE.

    Both implementations expose the same interface (get_underlying_price,
    get_historical_candles, get_intraday_ticks, get_atr, is_tradeable), so
    callers are unaffected by the choice.
    """
    global _provider
    if _provider is None:
        source = "yfinance"
        try:
            from uw_config import PRICE_SOURCE
            source = PRICE_SOURCE
        except Exception:
            pass
        if source == "uw":
            try:
                from uw_price_data import get_price_data
                candidate = get_price_data()

                # Without a key the UW provider returns empty results for every
                # call rather than raising — the bot would then skip every trade
                # for "no price available" and look merely quiet, not broken.
                # Prove it can actually serve a price before adopting it.
                if not candidate.api_key:
                    raise RuntimeError("UW_API_KEY not set")
                if candidate.get_underlying_price("SPY") is None:
                    raise RuntimeError("UW price probe returned nothing")

                _provider = candidate
                logger.info("📊 Price source: Unusual Whales (probe OK)")
                return _provider
            except Exception as e:
                logger.error(f"❌ UW price source unusable ({e}); falling back to yfinance")
        _provider = MarketDataProvider()
        logger.info("📊 Price source: yfinance")
    return _provider


def get_async_market_data() -> AsyncMarketDataAdapter:
    """Async-shaped provider for TechnicalGates."""
    global _async_adapter
    if _async_adapter is None:
        _async_adapter = AsyncMarketDataAdapter(get_market_data())
    return _async_adapter
