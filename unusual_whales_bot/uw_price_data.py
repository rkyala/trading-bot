"""
Unusual Whales Price Data — single-source replacement for yfinance

WHY
Everything price-related came from yfinance while all flow data came from UW.
Two sources means two clocks: a bar stamped 14:35 by yfinance and an alert
stamped 14:35 by UW are not guaranteed to describe the same moment, which is
precisely the alignment problem that corrupts options/price feature sets.

UW serves all of it, verified 2026-09-08:
    /stock/{t}/ohlc/1d      756 rows (~3 years)  -> MA20, RSI14, ATR14
    /stock/{t}/ohlc/1h      -> 200-SMA on the hourly
    /stock/{t}/ohlc/15m     -> 20-EMA on the 15-minute
    /stock/{t}/ohlc/5m      -> intraday VWAP
    /stock/{t}/stock-state  -> live quote
    every bar carries volume -> RVOL

Interface deliberately mirrors uw_market_data.MarketDataProvider so callers
(technical gates, execution safeguards, position marking) need no changes.

QUOTA
UW allows 80,000 calls/day; the bot used ~50 in a full session. Bars are cached
per (symbol, interval) with a short TTL, so a 20-symbol cycle costs ~20 calls.
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

BASE = "https://api.unusualwhales.com/api"

# UW uses its own tickers for index products; these are the ones that appear in
# flow and have no tradeable share.
INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "NDXP", "RUT", "VIX"}


class UWPriceData:
    """Price/OHLCV from Unusual Whales, cached."""

    def __init__(self, api_key: Optional[str] = None, cache_ttl: int = 60):
        self.api_key = api_key or os.getenv("UW_API_KEY")
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, object] = {}
        self._cache_at: Dict[str, float] = {}
        self._lock = threading.Lock()
        self.stats = {"calls": 0, "hits": 0, "misses": 0, "failures": 0}

        import requests
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            })

    # ------------------------------------------------------------------ util

    def _get(self, path: str, params: Optional[Dict] = None, ttl: Optional[int] = None):
        key = f"{path}:{sorted((params or {}).items())}"
        ttl = self.cache_ttl if ttl is None else ttl
        with self._lock:
            if key in self._cache and time.time() - self._cache_at.get(key, 0) < ttl:
                self.stats["hits"] += 1
                return self._cache[key]
        self.stats["misses"] += 1

        if not self.api_key:
            return None
        try:
            self.stats["calls"] += 1
            r = self.session.get(BASE + path, params=params or {}, timeout=10)
            if r.status_code != 200:
                logger.debug(f"{path} -> {r.status_code}")
                self.stats["failures"] += 1
                return None
            data = r.json().get("data")
            with self._lock:
                self._cache[key] = data
                self._cache_at[key] = time.time()
            return data
        except Exception as e:
            self.stats["failures"] += 1
            logger.debug(f"{path} failed: {e}")
            return None

    @staticmethod
    def _norm(rows: List[Dict], regular_only: bool = True) -> List[Dict]:
        """
        Normalise UW OHLC rows to the shape the rest of the bot expects.

        CRITICAL — UW returns THREE rows per period, one per session:
            market_time 'pr' = pre-market, 'r' = regular, 'po' = post-market
        e.g. /ohlc/1d returned 756 rows for 252 trading days.

        Mixing them silently corrupts every indicator. Pre-market bars have
        tiny ranges, so an ATR computed over interleaved sessions came out
        25-35% BELOW the true value when cross-checked against yfinance —
        which would have made every stop roughly a third too tight.

        Regular-hours rows only, oldest-first (indicators slice with
        [-period:], so order matters).
        """
        out = []
        for r in rows or []:
            if regular_only and r.get("market_time") not in (None, "r"):
                continue
            try:
                ts = r.get("start_time") or r.get("date") or r.get("end_time")
                out.append({
                    "date": ts,
                    "time": ts,
                    "market_time": r.get("market_time"),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r.get("volume") or r.get("total_volume") or 0),
                })
            except (KeyError, TypeError, ValueError):
                continue
        out.sort(key=lambda x: str(x["date"]))
        return out

    # ------------------------------------------------------------------- API

    # ---------------------------------------------------------------------
    # Symbols UW does not serve. Verified 2026-09-08: /stock/VIX/* returns 422
    # for every interval. VIXY exists but tracks VIX FUTURES with roll decay,
    # so its level is not comparable to VIX thresholds ("VIX > 22") and using
    # it as a proxy would silently mis-scale the regime model.
    #
    # VIX drives two of the three macro price thresholds, so leaving it None
    # would quietly disable half the risk-off detection. This narrow fallback
    # is preferable to that, and is announced rather than silent.
    # ---------------------------------------------------------------------
    UNSUPPORTED = {"VIX", "^VIX", "VVIX"}

    def _yf_fallback_price(self, symbol: str) -> Optional[float]:
        try:
            from uw_market_data import MarketDataProvider
            if not hasattr(self, "_yf"):
                self._yf = MarketDataProvider()
                logger.info(f"📊 {symbol}: not served by UW — using yfinance for this symbol only")
            return self._yf.get_underlying_price(symbol)
        except Exception as e:
            logger.debug(f"yfinance fallback failed for {symbol}: {e}")
            return None

    def get_underlying_price(self, symbol: str) -> Optional[float]:
        """Latest price. Returns None if unavailable — callers must skip, not guess."""
        if symbol.upper() in self.UNSUPPORTED:
            return self._yf_fallback_price(symbol)
        d = self._get(f"/stock/{symbol.upper()}/stock-state", ttl=30)
        if isinstance(d, dict):
            try:
                px = float(d.get("close") or 0)
                if px > 0:
                    return px
            except (TypeError, ValueError):
                pass
        bars = self.get_bars(symbol, "5m", limit=3)
        return bars[-1]["close"] if bars else None

    def get_bars(self, symbol: str, interval: str = "1d", limit: int = 60) -> List[Dict]:
        """OHLCV bars. interval: 1d | 1h | 30m | 15m | 5m | 1m"""
        if symbol.upper() in self.UNSUPPORTED:
            try:
                from uw_market_data import MarketDataProvider
                if not hasattr(self, "_yf"):
                    self._yf = MarketDataProvider()
                iv = "day" if interval == "1d" else "hour"
                return self._yf.get_historical_candles(symbol, iv, limit)
            except Exception:
                return []
        # NOTE: UW ignores the limit param (asked 20, received 756), so the
        # slice happens locally AFTER filtering to regular-hours rows.
        d = self._get(f"/stock/{symbol.upper()}/ohlc/{interval}",
                      {"limit": limit},
                      ttl=300 if interval == "1d" else 60)
        bars = self._norm(d if isinstance(d, list) else [])
        return bars[-limit:] if limit else bars

    # --- interface-compatible with the old yfinance provider ---------------

    def get_historical_candles(self, symbol: str, interval: str = "day",
                               limit: int = 30) -> List[Dict]:
        iv = {"day": "1d", "1d": "1d", "hour": "1h", "1h": "1h"}.get(interval, "1d")
        return self.get_bars(symbol, iv, limit=max(limit, 30))

    def get_intraday_ticks(self, symbol: str, interval: str = "5m") -> List[Dict]:
        return self.get_bars(symbol, interval, limit=200)

    def get_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        bars = self.get_bars(symbol, "1d", limit=period + 20)  # 1d ignores limit anyway
        if len(bars) < period + 1:
            return None
        df = pd.DataFrame(bars)
        prev = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - prev).abs(),
                        (df["low"] - prev).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if pd.notna(atr) and atr > 0 else None

    def is_tradeable(self, symbol: str) -> bool:
        return symbol.upper() not in INDEX_SYMBOLS

    # --- indicators the screener spec needs --------------------------------

    # Roughly one row in three is regular-hours (pre/regular/post), so a
    # request for N raw rows yields only ~N/3 usable bars. Over-request by 4x
    # plus a buffer, or a 200-period SMA silently returns None.
    _SESSION_OVERSAMPLE = 4

    def get_ema(self, symbol: str, period: int, interval: str) -> Optional[float]:
        bars = self.get_bars(symbol, interval,
                             limit=period * self._SESSION_OVERSAMPLE + 50)
        if len(bars) < period:
            return None
        closes = pd.Series([b["close"] for b in bars])
        return float(closes.ewm(span=period, adjust=False).mean().iloc[-1])

    def get_sma(self, symbol: str, period: int, interval: str) -> Optional[float]:
        bars = self.get_bars(symbol, interval,
                             limit=period * self._SESSION_OVERSAMPLE + 50)
        if len(bars) < period:
            return None
        return float(np.mean([b["close"] for b in bars[-period:]]))

    def get_vwap(self, symbol: str, interval: str = "5m") -> Optional[float]:
        bars = self.get_bars(symbol, interval, limit=200)
        if len(bars) < 2:
            return None
        df = pd.DataFrame(bars)
        # Session-only: VWAP resets daily, so a multi-day bar set would be wrong.
        last_day = str(df["date"].iloc[-1])[:10]
        df = df[df["date"].astype(str).str[:10] == last_day]
        if df.empty or df["volume"].sum() <= 0:
            return None
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        return float((tp * df["volume"]).sum() / df["volume"].sum())

    def get_rvol(self, symbol: str, lookback_days: int = 20) -> Optional[float]:
        """
        Relative volume: today's volume so far vs the average full day.

        Compared against the same elapsed fraction of prior sessions would be
        stricter; this simpler form is what the screener spec asks for and is
        adequate as a >1.2 threshold check.
        """
        daily = self.get_bars(symbol, "1d", limit=lookback_days + 2)
        if len(daily) < lookback_days:
            return None
        today = daily[-1]["volume"]
        prior = [b["volume"] for b in daily[-(lookback_days + 1):-1] if b["volume"] > 0]
        if not prior or today <= 0:
            return None
        return float(today / np.mean(prior))

    def log_stats(self):
        s = self.stats
        logger.info(
            f"📊 UW price data: {s['calls']} calls, {s['hits']} cache hits, "
            f"{s['failures']} failures"
        )


_provider: Optional[UWPriceData] = None


def get_price_data() -> UWPriceData:
    global _provider
    if _provider is None:
        _provider = UWPriceData()
    return _provider
