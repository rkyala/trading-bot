#!/usr/bin/env python3
"""
Market Regime Detection using Finnhub API + ADX
Routes capital to breakout (trending) or mean-reversion (ranging) strategies
"""

import requests
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta

class FinnhubRegimeFilter:
    """Detect market regime using Finnhub API (no rate limiting issues)"""

    def __init__(self):
        self.trending_threshold = 25
        self.ranging_threshold = 20
        self.lookback = 60

        # Load config
        try:
            with open("finnhub_config.json", "r") as f:
                config = json.load(f)
                self.api_key = config.get("api_key")
                self.base_url = config.get("base_url", "https://finnhub.io/api/v1")
        except:
            self.api_key = None
            self.base_url = "https://finnhub.io/api/v1"

        if not self.api_key or self.api_key == "YOUR_FINNHUB_API_KEY_HERE":
            print("⚠️  Finnhub API key not configured!")
            print("   1. Go to https://finnhub.io/ (free account)")
            print("   2. Copy your API key")
            print("   3. Paste it in finnhub_config.json")
            print("   4. Run this script again")
            self.api_key = None

    def get_candles(self, symbol, resolution="D"):
        """Fetch historical candles from Finnhub"""
        if not self.api_key:
            return None

        try:
            end_time = int(datetime.now().timestamp())
            start_time = int((datetime.now() - timedelta(days=180)).timestamp())

            url = f"{self.base_url}/stock/candle"
            params = {
                "symbol": symbol,
                "resolution": resolution,
                "from": start_time,
                "to": end_time,
                "token": self.api_key
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data.get("s") == "ok":
                    df = pd.DataFrame({
                        "Close": data["c"],
                        "High": data["h"],
                        "Low": data["l"],
                        "Volume": data["v"],
                        "Open": data["o"]
                    })
                    return df
                else:
                    # Debug: print API response
                    print(f"\n   API Response: {data}")
                    return None
            else:
                print(f"\n   Status Code: {response.status_code}")
                print(f"   Response: {response.text}")
                return None

        except Exception as e:
            print(f"\n   Exception: {e}")
            return None

    def calculate_adx(self, df, period=14):
        """Calculate ADX from candle data"""
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
        Determine market regime using Finnhub data
        Returns: (regime: str, adx: float, details: dict)
        """
        # Fetch data
        df = self.get_candles(symbol)

        if df is None:
            return "UNKNOWN", 0, {"error": "Failed to fetch data"}

        # Calculate ADX
        adx, plus_di, minus_di = self.calculate_adx(df, period=14)

        if adx is None:
            return "UNKNOWN", 0, {"error": "Insufficient data for ADX"}

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

        return regime, latest_adx, details


if __name__ == "__main__":
    regime_filter = FinnhubRegimeFilter()

    if not regime_filter.api_key:
        print("\n❌ API key required! Cannot proceed.")
        exit(1)

    symbols = ["AAPL", "MSFT", "NVDA", "TSLA"]

    print("=" * 100)
    print("MARKET REGIME DETECTION (Finnhub + ADX)")
    print("=" * 100)
    print()

    for symbol in symbols:
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
            print(f"❌ ERROR: {details['error']}")

        print()
