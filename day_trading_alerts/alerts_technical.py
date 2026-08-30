#!/usr/bin/env python3
"""
Technical Analysis Signals for Day Trading Alerts
Phase 1: RSI, Bollinger Bands, MACD, Volume
"""

import logging
from typing import Dict, List, Optional
import numpy as np

log = logging.getLogger(__name__)

class TechnicalAnalysis:
    """Calculate technical indicators for alert signals"""

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
        """
        Calculate RSI (Relative Strength Index)

        RSI < 30: Oversold (bullish)
        RSI > 70: Overbought (bearish)
        """
        if len(prices) < period + 1:
            return None

        prices = np.array(prices[-period-1:], dtype=float)
        deltas = np.diff(prices)

        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi)

    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Optional[Dict[str, float]]:
        """
        Calculate Bollinger Bands (20-period SMA ± 2σ)

        Price < Lower Band: Oversold (bullish)
        Price > Upper Band: Overbought (bearish)
        """
        if len(prices) < period:
            return None

        prices = np.array(prices[-period:], dtype=float)
        sma = np.mean(prices)
        std = np.std(prices)

        upper_band = sma + (std_dev * std)
        lower_band = sma - (std_dev * std)

        return {
            "sma": float(sma),
            "upper_band": float(upper_band),
            "lower_band": float(lower_band),
            "std_dev": float(std)
        }

    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Dict[str, float]]:
        """
        Calculate MACD (Moving Average Convergence Divergence)

        MACD > Signal Line: Bullish
        MACD < Signal Line: Bearish
        Histogram: MACD - Signal (positive = bullish momentum)
        """
        if len(prices) < slow + signal:
            return None

        prices = np.array(prices, dtype=float)

        ema_fast = TechnicalAnalysis._ema(prices, fast)
        ema_slow = TechnicalAnalysis._ema(prices, slow)

        macd_line = ema_fast - ema_slow

        macd_array = np.array([macd_line] * len(prices))
        macd_line_full = TechnicalAnalysis._ema(macd_array, signal)
        signal_line = macd_line_full

        histogram = macd_line - signal_line

        return {
            "macd": float(macd_line),
            "signal": float(signal_line),
            "histogram": float(histogram)
        }

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(data) < period:
            return float(np.mean(data))

        multiplier = 2 / (period + 1)
        ema = float(np.mean(data[:period]))

        for i in range(period, len(data)):
            ema = data[i] * multiplier + ema * (1 - multiplier)

        return ema

    @staticmethod
    def calculate_volume_spike(current_volume: float, avg_volume: float, threshold: float = 2.0) -> bool:
        """Check if volume spiked above average"""
        if avg_volume <= 0:
            return False
        return current_volume > (avg_volume * threshold)

    @staticmethod
    def score_signal(symbol: str, candles: List[Dict], current_price: float) -> Dict:
        """
        Score technical setup 0-100

        Returns:
        {
            "symbol": str,
            "confidence": int (0-100),
            "rsi": float,
            "bb_position": str (lower/middle/upper),
            "macd_signal": str (bullish/bearish),
            "volume_spike": bool,
            "reason": str
        }
        """
        if not candles or len(candles) < 20:
            return {
                "symbol": symbol,
                "confidence": 0,
                "reason": "Insufficient candle data"
            }

        # Extract OHLCV
        closes = [c.get("close", c.get("c")) for c in candles]
        volumes = [c.get("volume", c.get("v")) for c in candles]

        if not closes or not volumes:
            return {
                "symbol": symbol,
                "confidence": 0,
                "reason": "Missing OHLCV data"
            }

        # Calculate indicators
        rsi = TechnicalAnalysis.calculate_rsi(closes, period=14)
        bb = TechnicalAnalysis.calculate_bollinger_bands(closes, period=20)
        macd = TechnicalAnalysis.calculate_macd(closes)

        avg_volume = np.mean(volumes[-10:])  # Last 10 candles average
        volume_spike = TechnicalAnalysis.calculate_volume_spike(volumes[-1], avg_volume, threshold=1.5)

        # Build signal confidence
        confidence = 0
        reasons = []

        # RSI component
        if rsi is not None:
            if rsi < 30:
                confidence += 30
                reasons.append(f"RSI {rsi:.0f} (Oversold)")
            elif rsi > 70:
                confidence += 15
                reasons.append(f"RSI {rsi:.0f} (Overbought)")
            elif 40 < rsi < 60:
                confidence += 5
                reasons.append(f"RSI {rsi:.0f} (Neutral)")

        # Bollinger Bands component
        if bb:
            bb_position = "middle"
            if current_price <= bb["lower_band"] * 1.02:
                confidence += 25
                bb_position = "lower"
                reasons.append("BB Lower Band (Support)")
            elif current_price >= bb["upper_band"] * 0.98:
                confidence += 20
                bb_position = "upper"
                reasons.append("BB Upper Band (Resistance)")
            else:
                bb_position = "middle"

        # MACD component
        if macd:
            if macd["histogram"] > 0 and macd["macd"] > macd["signal"]:
                confidence += 20
                reasons.append(f"MACD Bullish (Histogram +{macd['histogram']:.2f})")
            elif macd["histogram"] < 0 and macd["macd"] < macd["signal"]:
                confidence += 15
                reasons.append(f"MACD Bearish")

        # Volume component
        if volume_spike:
            confidence += 10
            reasons.append("Volume Spike")

        # Cap confidence at 100
        confidence = min(confidence, 100)

        return {
            "symbol": symbol,
            "confidence": int(confidence),
            "rsi": rsi,
            "bb": bb,
            "macd": macd,
            "volume_spike": volume_spike,
            "reason": " | ".join(reasons) if reasons else "Weak signal"
        }


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Mock data
    closes = [100 + i + (i % 3 - 1.5) for i in range(100)]
    volumes = [1000000 + i * 1000 for i in range(100)]

    # Create mock candles
    candles = []
    for i in range(len(closes)):
        candles.append({
            "close": closes[i],
            "high": closes[i] + 1,
            "low": closes[i] - 1,
            "open": closes[i] - 0.5,
            "volume": volumes[i],
            "time": i * 300  # 5-min candles
        })

    ta = TechnicalAnalysis()
    signal = ta.score_signal("TEST", candles, closes[-1])

    print(f"\nSignal Score: {signal['confidence']}/100")
    print(f"Reason: {signal['reason']}")
    print(f"RSI: {signal.get('rsi')}")
