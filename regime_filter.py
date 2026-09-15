#!/usr/bin/env python3
"""
Market Regime Detection using yfinance (with local caching)
Routes capital to breakout (trending) or mean-reversion (ranging) strategies
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

class CachedYFinanceRegimeFilter:
    """Detect market regime using yfinance with local cache to avoid rate limiting"""

    def __init__(self):
        self.trending_threshold = 25
        self.ranging_threshold = 20
        self.cache_dir = "regime_cache"
        self.cache_ttl_hours = 24

        # Create cache directory
        Path(self.cache_dir).mkdir(exist_ok=True)

    def get_cache_file(self, symbol):
        """Get cache file path for symbol"""
        return f"{self.cache_dir}/{symbol}_regime.json"

    def load_cache(self, symbol):
        """Load cached data if still fresh"""
        cache_file = self.get_cache_file(symbol)

        try:
            if Path(cache_file).exists():
                with open(cache_file, "r") as f:
                    cache = json.load(f)

                # Check if cache is fresh
                cached_time = datetime.fromisoformat(cache.get("timestamp", "1970-01-01"))
                age_hours = (datetime.now() - cached_time).total_seconds() / 3600

                if age_hours < self.cache_ttl_hours:
                    return cache.get("regime"), cache.get("adx"), cache.get("details")
        except:
            pass

        return None, None, None

    def save_cache(self, symbol, regime, adx, details):
        """Save regime data to cache"""
        cache_file = self.get_cache_file(symbol)

        try:
            cache = {
                "timestamp": datetime.now().isoformat(),
                "regime": regime,
                "adx": adx,
                "details": details
            }

            with open(cache_file, "w") as f:
                json.dump(cache, f)
        except:
            pass

    def calculate_adx(self, df, period=14):
        """Calculate ADX from price data"""
        if df is None or len(df) < period:
            return None, None, None

        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()

        # Directional Movements
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where(plus_dm > 0, 0)
        minus_dm = minus_dm.where(minus_dm > 0, 0)

        plus_dm = plus_dm.where((plus_dm > minus_dm) | (minus_dm == 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) | (plus_dm == 0), 0)

        # Directional Indicators
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

        # DX and ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(period).mean()

        return adx, plus_di, minus_di

    def get_regime(self, symbol):
        """
        Determine market regime
        Returns: (regime: str, adx: float, details: dict)
        """
        # Check cache first
        cached_regime, cached_adx, cached_details = self.load_cache(symbol)
        if cached_regime is not None:
            return cached_regime, cached_adx, cached_details

        try:
            # Fetch data from yfinance
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="6mo")

            if len(hist) < 60:
                return "UNKNOWN", 0, {"error": "Insufficient data"}

            # Calculate ADX
            adx, plus_di, minus_di = self.calculate_adx(hist, period=14)

            if adx is None:
                return "UNKNOWN", 0, {"error": "ADX calculation failed"}

            latest_adx = adx.iloc[-1]
            latest_plus_di = plus_di.iloc[-1]
            latest_minus_di = minus_di.iloc[-1]

            # Determine regime
            if latest_adx > self.trending_threshold:
                regime = "TRENDING"
            elif latest_adx < self.ranging_threshold:
                regime = "RANGING"
            else:
                regime = "TRANSITION"

            details = {
                "adx": round(latest_adx, 2),
                "plus_di": round(latest_plus_di, 2),
                "minus_di": round(latest_minus_di, 2),
                "trend_strength": "Strong" if latest_plus_di > latest_minus_di else "Weak"
            }

            # Cache the result
            self.save_cache(symbol, regime, latest_adx, details)

            return regime, latest_adx, details

        except Exception as e:
            return "ERROR", 0, {"error": str(e)}


if __name__ == "__main__":
    regime_filter = CachedYFinanceRegimeFilter()

    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"]

    print("=" * 100)
    print("MARKET REGIME DETECTION (yfinance with Local Caching)")
    print("=" * 100)
    print()

    for i, symbol in enumerate(symbols):
        print(f"Fetching {symbol}...", end=" ", flush=True)

        regime, adx, details = regime_filter.get_regime(symbol)

        if regime == "TRENDING":
            mode = "🔥 BREAKOUT MODE"
        elif regime == "RANGING":
            mode = "🔄 MEAN-REVERSION MODE"
        else:
            mode = "⚠️  TRANSITION"

        if "error" not in details:
            print(f"✅")
            print(f"  {symbol:6} | ADX: {adx:6.2f} | Regime: {regime:11} | {mode}")
            print(f"          | +DI: {details['plus_di']:6.2f} | -DI: {details['minus_di']:6.2f} | Trend: {details['trend_strength']}")
        else:
            print(f"❌ {details['error']}")

        print()

        # Rate limiting: 2 seconds between requests
        if i < len(symbols) - 1:
            time.sleep(2)

    print("=" * 100)
    print("💾 Data cached locally for 24 hours (no API calls on refresh)")
    print("=" * 100)
