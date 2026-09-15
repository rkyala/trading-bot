#!/usr/bin/env python3
"""Debug VCP detector to see why no breakouts are found"""

import yfinance as yf
import pandas as pd
from breakout_detector import VCPBreakoutDetector

detector = VCPBreakoutDetector()

# Test one symbol in detail
symbol = "AAPL"
print(f"Debugging VCP conditions for {symbol}...\n")

try:
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="2y")

    close = hist['Close'].iloc[-1]
    high = hist['High'].iloc[-1]
    volume = hist['Volume'].iloc[-1]
    high_20d = hist['High'].iloc[-20:].max()

    print(f"Current Price: ${close:.2f}")
    print(f"20-Day High: ${high_20d:.2f}")
    print(f"Current Volume: {volume:,.0f}")
    print()

    # 1. Trend Filter
    sma_50 = hist['Close'].rolling(50).mean().iloc[-1]
    sma_200 = hist['Close'].rolling(200).mean()
    sma_200_current = sma_200.iloc[-1]
    sma_200_slope = (sma_200.iloc[-1] - sma_200.iloc[-20]) / 20

    print("1. TREND FILTER:")
    print(f"   Close (${close:.2f}) > SMA_50 (${sma_50:.2f}): {close > sma_50}")
    print(f"   SMA_50 (${sma_50:.2f}) > SMA_200 (${sma_200_current:.2f}): {sma_50 > sma_200_current}")
    print(f"   SMA_200 Slope ({sma_200_slope:.4f}) > 0: {sma_200_slope > 0}")
    trend_ok = (close > sma_50) and (sma_50 > sma_200_current) and (sma_200_slope > 0)
    print(f"   ✅ PASS" if trend_ok else f"   ❌ FAIL")
    print()

    # 2. Volatility Compression
    atr = detector.calculate_atr(hist['High'], hist['Low'], hist['Close'], period=14)
    atr_50 = detector.calculate_atr(hist['High'], hist['Low'], hist['Close'], period=50)

    atr_14_current = atr.iloc[-1]
    atr_50_current = atr_50.iloc[-1]
    atr_ratio = atr_14_current / atr_50_current if atr_50_current > 0 else 1

    print("2. VOLATILITY COMPRESSION:")
    print(f"   ATR_14: {atr_14_current:.4f}")
    print(f"   ATR_50: {atr_50_current:.4f}")
    print(f"   Ratio (ATR_14 / ATR_50): {atr_ratio:.4f}")
    print(f"   Ratio < 0.65: {atr_ratio < 0.65}")
    vol_compressed = atr_ratio < 0.65
    print(f"   ✅ PASS" if vol_compressed else f"   ❌ FAIL")
    print()

    # 3. Breakout Signal
    vol_50d_avg = hist['Volume'].rolling(50).mean().iloc[-1]
    vol_threshold = vol_50d_avg * 1.5

    print("3. BREAKOUT SIGNAL:")
    print(f"   Close (${close:.2f}) > 20-Day High (${high_20d:.2f}): {close > high_20d}")
    print(f"   Current Volume ({volume:,.0f}) >= 1.5x Avg ({vol_threshold:,.0f}): {volume >= vol_threshold}")
    breakout_on_volume = (close > high_20d) and (volume >= vol_threshold)
    print(f"   ✅ PASS" if breakout_on_volume else f"   ❌ FAIL")
    print()

    # 4. Strong Position
    distance_to_high = ((high_20d - close) / close) * 100
    strong_position = distance_to_high <= 5

    print("4. STRONG POSITION:")
    print(f"   Distance to 20-Day High: {distance_to_high:.2f}%")
    print(f"   Within 5% of High: {strong_position}")
    print(f"   ✅ PASS" if strong_position else f"   ❌ FAIL")
    print()

    # Summary
    conditions_passed = sum([trend_ok, vol_compressed, breakout_on_volume, strong_position])
    print("=" * 80)
    print(f"CONDITIONS PASSED: {conditions_passed}/4 (Need 3/4)")
    print("=" * 80)

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
