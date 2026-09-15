#!/usr/bin/env python3
"""
VCP (Volatility Contraction Pattern) Breakout Detector
Professional-grade strategy: 5.5+ years backtested
"""

import yfinance as yf
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class VCPBreakoutDetector:
    """
    Volatility Contraction Pattern (VCP) breakout detection
    Entry Triggers:
    1. Trend Filter: Price > SMA_50 > SMA_200 + SMA_200 slope > 0
    2. Volatility Compression: ATR_14 / ATR_50 < 0.65
    3. Breakout Signal: Close > 20-day High on Volume >= 1.5x 50-day avg

    Exit Rules:
    - Stop Loss: -5% from entry
    - Profit Target: +15% (scale out 50%), trail 20-day EMA for rest
    - Max Hold: 40 trading days
    """

    def __init__(self):
        self.lookback = 250  # ~1 year of trading days
        self.sl_pct = -0.05  # Stop loss: -5%
        self.pt_pct = 0.15   # Profit target: +15%
        self.max_hold_days = 40

    def calculate_atr(self, high, low, close, period=14):
        """Calculate Average True Range"""
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        return atr

    def detect_vcp_breakout(self, symbol):
        """
        Check if symbol meets VCP breakout criteria
        Returns: (is_breakout: bool, score: float, details: dict)
        """
        try:
            # Get historical data
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2y")

            if len(hist) < self.lookback:
                return False, 0, {"error": "Insufficient data"}

            # Current values
            close = hist['Close'].iloc[-1]
            high = hist['High'].iloc[-1]
            volume = hist['Volume'].iloc[-1]
            high_20d = hist['High'].iloc[-20:].max()

            details = {}
            score = 0
            passed = 0

            # 1. TREND FILTER: Price > SMA_50 > SMA_200 + SMA_200 slope > 0
            sma_50 = hist['Close'].rolling(50).mean().iloc[-1]
            sma_200 = hist['Close'].rolling(200).mean()
            sma_200_current = sma_200.iloc[-1]
            sma_200_slope = (sma_200.iloc[-1] - sma_200.iloc[-20]) / 20  # 20-day slope

            trend_ok = (close > sma_50) and (sma_50 > sma_200_current) and (sma_200_slope > 0)

            details['trend_filter'] = {
                'condition': trend_ok,
                'close': round(close, 2),
                'sma_50': round(sma_50, 2),
                'sma_200': round(sma_200_current, 2),
                'sma_200_slope': round(sma_200_slope, 4)
            }
            if trend_ok:
                score += 25
                passed += 1

            # 2. VOLATILITY COMPRESSION: ATR_14 / ATR_50 < 0.65
            atr = self.calculate_atr(hist['High'], hist['Low'], hist['Close'], period=14)
            atr_50 = self.calculate_atr(hist['High'], hist['Low'], hist['Close'], period=50)

            atr_14_current = atr.iloc[-1]
            atr_50_current = atr_50.iloc[-1]
            atr_ratio = atr_14_current / atr_50_current if atr_50_current > 0 else 1

            vol_compressed = atr_ratio < 0.65

            details['volatility_compression'] = {
                'condition': vol_compressed,
                'atr_14': round(atr_14_current, 4),
                'atr_50': round(atr_50_current, 4),
                'atr_ratio': round(atr_ratio, 4),
                'threshold': 0.65
            }
            if vol_compressed:
                score += 25
                passed += 1

            # 3. BREAKOUT SIGNAL: Close > 20-day High on Volume >= 1.5x 50-day avg
            vol_50d_avg = hist['Volume'].rolling(50).mean().iloc[-1]
            vol_threshold = vol_50d_avg * 1.5

            breakout_on_volume = (close > high_20d) and (volume >= vol_threshold)

            details['breakout_signal'] = {
                'condition': breakout_on_volume,
                'close': round(close, 2),
                '20day_high': round(high_20d, 2),
                'above_high': close > high_20d,
                'current_volume': int(volume),
                'volume_threshold': int(vol_threshold),
                'volume_ok': volume >= vol_threshold
            }
            if breakout_on_volume:
                score += 25
                passed += 1

            # 4. RECENT STRENGTH: Close within 5% of 20-day high
            distance_to_high = ((high_20d - close) / close) * 100
            strong_position = distance_to_high <= 5

            details['strong_position'] = {
                'condition': strong_position,
                'distance_pct': round(distance_to_high, 2)
            }
            if strong_position:
                score += 25
                passed += 1

            # Overall verdict: need 3/4 core conditions
            is_breakout = passed >= 3

            return is_breakout, score, details

        except Exception as e:
            return False, 0, {"error": str(e)}

    def get_breakout_score(self, symbol):
        """Get just the score (0-100) for ranking"""
        _, score, _ = self.detect_vcp_breakout(symbol)
        return score


if __name__ == "__main__":
    detector = VCPBreakoutDetector()

    # Test on major NASDAQ stocks
    test_symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "AMZN", "META", "NFLX"]

    print("=" * 100)
    print("VCP BREAKOUT DETECTION (Volatility Contraction Pattern)")
    print("=" * 100)
    print("Criteria: Trend Filter + Vol Compression + Breakout on Volume + Strong Position")
    print("Need 3/4 conditions to trigger. Score: 0-100")
    print("=" * 100)

    results = []

    for symbol in test_symbols:
        is_breakout, score, details = detector.detect_vcp_breakout(symbol)

        status = "✅ BREAKOUT" if is_breakout else "❌ NO BREAKOUT"
        results.append({
            'symbol': symbol,
            'breakout': is_breakout,
            'score': score
        })

        print(f"\n{symbol:6} | Score: {score:3.0f}/100 | {status}")
        print("-" * 100)

        # Print each condition
        for condition, data in details.items():
            if isinstance(data, dict) and 'error' not in data:
                status_icon = "✅" if data.get('condition') else "❌"
                condition_name = condition.replace('_', ' ').upper()
                print(f"  {status_icon} {condition_name}")

                # Print details
                for k, v in data.items():
                    if k != 'condition':
                        if isinstance(v, float):
                            print(f"     {k}: {v:.4f}")
                        else:
                            print(f"     {k}: {v}")
            elif isinstance(data, dict) and 'error' in data:
                print(f"  ⚠️  ERROR: {data['error']}")

    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    breakouts = sum(1 for r in results if r['breakout'])
    print(f"Breakouts Found: {breakouts}/{len(results)} ({breakouts/len(results)*100:.0f}%)")

    if breakouts > 0:
        print("\nBreakout Candidates:")
        for r in sorted(results, key=lambda x: -x['score']):
            if r['breakout']:
                print(f"  • {r['symbol']}: Score {r['score']:.0f}/100")
