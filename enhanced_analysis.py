#!/usr/bin/env python3
"""
Enhanced Technical Analysis for Llama
- Calculates RSI, VWAP, Bollinger Bands
- Provides context for better decisions
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class TechnicalAnalyzer:
    """Calculate advanced technical indicators"""

    @staticmethod
    def calculate_rsi(prices, period=14):
        """Calculate Relative Strength Index"""
        if len(prices) < period + 1:
            return 50  # Neutral if not enough data

        deltas = np.diff(prices)
        seed = deltas[:period+1]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period

        rs = up / down if down != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def calculate_vwap(high, low, close, volume):
        """Calculate Volume Weighted Average Price"""
        tp = (high + low + close) / 3
        vwap = (tp * volume).sum() / volume.sum()
        return vwap

    @staticmethod
    def calculate_bollinger_bands(prices, period=20, std_dev=2):
        """Calculate Bollinger Bands"""
        sma = pd.Series(prices).rolling(window=period).mean().iloc[-1]
        std = pd.Series(prices).rolling(window=period).std().iloc[-1]
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower

    @staticmethod
    def calculate_macd(prices, fast=12, slow=26, signal=9):
        """Calculate MACD"""
        ema_fast = pd.Series(prices).ewm(span=fast).mean().iloc[-1]
        ema_slow = pd.Series(prices).ewm(span=slow).mean().iloc[-1]
        macd = ema_fast - ema_slow
        return macd

    @staticmethod
    def get_technical_context(symbol):
        """Get full technical analysis for a symbol"""
        try:
            ticker = yf.Ticker(symbol)

            # Get data
            hist = ticker.history(period="60d")
            if len(hist) < 20:
                return None

            prices = hist['Close'].values
            high = hist['High'].values
            low = hist['Low'].values
            volume = hist['Volume'].values
            current_price = prices[-1]

            # Calculate indicators
            rsi = TechnicalAnalyzer.calculate_rsi(prices, period=14)
            vwap = TechnicalAnalyzer.calculate_vwap(high, low, prices, volume)
            bb_upper, bb_middle, bb_lower = TechnicalAnalyzer.calculate_bollinger_bands(prices)
            macd = TechnicalAnalyzer.calculate_macd(prices)

            # Determine trend
            sma_20 = pd.Series(prices).rolling(20).mean().iloc[-1]
            sma_50 = pd.Series(prices).rolling(50).mean().iloc[-1] if len(prices) >= 50 else sma_20

            trend = "UPTREND" if current_price > sma_20 > sma_50 else \
                    "DOWNTREND" if current_price < sma_20 < sma_50 else \
                    "RANGING"

            # Distance from key levels
            distance_to_upper_bb = ((bb_upper - current_price) / current_price) * 100
            distance_to_lower_bb = ((current_price - bb_lower) / current_price) * 100

            return {
                "current_price": float(current_price),
                "rsi": float(rsi),
                "rsi_signal": "OVERBOUGHT" if rsi > 70 else "OVERSOLD" if rsi < 30 else "NEUTRAL",
                "vwap": float(vwap),
                "vwap_signal": "ABOVE" if current_price > vwap else "BELOW",
                "bb_upper": float(bb_upper),
                "bb_middle": float(bb_middle),
                "bb_lower": float(bb_lower),
                "distance_to_upper_bb": float(distance_to_upper_bb),
                "distance_to_lower_bb": float(distance_to_lower_bb),
                "macd": float(macd),
                "trend": trend,
                "sma_20": float(sma_20),
                "sma_50": float(sma_50),
            }
        except Exception as e:
            print(f"Error getting technical context for {symbol}: {e}")
            return None


# Test
if __name__ == "__main__":
    analyzer = TechnicalAnalyzer()
    context = analyzer.get_technical_context("MSFT")
    if context:
        print("MSFT Technical Analysis:")
        for key, val in context.items():
            print(f"  {key}: {val}")
