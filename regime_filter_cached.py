#!/usr/bin/env python3
"""
Market Regime Detection using Bot's Cached Market Data
No API calls needed - reads from market_*_cache.json files
"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path

class CachedRegimeFilter:
    """Detect market regime from cached OHLCV data"""

    def __init__(self):
        self.trending_threshold = 25
        self.ranging_threshold = 20

    def load_cached_data(self, symbol):
        """Load cached market data from bot's cache files"""
        try:
            # Look for market_SYMBOL_cache.json
            cache_file = f"market_{symbol}_cache.json"

            if not Path(cache_file).exists():
                return None

            with open(cache_file, "r") as f:
                data = json.load(f)

            if not data or len(data) < 60:
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.sort_values("timestamp")

            return df[["timestamp", "open", "high", "low", "close", "volume"]].copy()

        except Exception as e:
            return None

    def calculate_adx(self, df, period=14):
        """Calculate ADX from cached data"""
        if df is None or len(df) < period:
            return None, None, None

        high = df["high"]
        low = df["low"]
        close = df["close"]

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
        Determine market regime from cached data
        Returns: (regime: str, adx: float, details: dict)
        """
        # Load cached data
        df = self.load_cached_data(symbol)

        if df is None:
            return "UNKNOWN", 0, {"error": f"No cached data for {symbol}"}

        # Calculate ADX
        adx, plus_di, minus_di = self.calculate_adx(df, period=14)

        if adx is None:
            return "UNKNOWN", 0, {"error": "Insufficient historical data"}

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
            "trend_strength": "Strong" if latest_plus_di > latest_minus_di else "Weak",
            "data_points": len(df)
        }

        return regime, latest_adx, details


if __name__ == "__main__":
    regime_filter = CachedRegimeFilter()

    # Test with symbols that bot has cached
    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN"]

    print("=" * 100)
    print("MARKET REGIME DETECTION (From Bot's Cached Data)")
    print("=" * 100)
    print()

    found_any = False

    for symbol in symbols:
        regime, adx, details = regime_filter.get_regime(symbol)

        if "error" not in details:
            found_any = True

            if regime == "TRENDING":
                mode = "🔥 BREAKOUT MODE"
            elif regime == "RANGING":
                mode = "🔄 MEAN-REVERSION MODE"
            else:
                mode = "⚠️  TRANSITION"

            print(f"{symbol:6} | ADX: {adx:6.2f} | Regime: {regime:11} | {mode}")
            print(f"        | +DI: {details['plus_di']:6.2f} | -DI: {details['minus_di']:6.2f} | Trend: {details['trend_strength']}")
            print(f"        | Data points: {details['data_points']}")
            print()

    if not found_any:
        print("❌ No cached market data found!")
        print("\nThe bot needs to run and collect market data first.")
        print("Cache files should be created at: market_SYMBOL_cache.json")
        print("\nEnsure bot is running: python3 bot_dry_run_v3_5.py")
