#!/usr/bin/env python3
"""
Advanced Chart Analysis - Volume, Pivots, Confluence, ATR, Fibonacci
Feeds into Llama for smarter entry decisions
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class AdvancedChartAnalyzer:
    """Advanced technical analysis for better trading signals"""

    def __init__(self):
        self.cache = {}

    def get_chart_analysis(self, symbol, period="60d"):
        """
        Get comprehensive chart analysis

        Returns:
            {
                "volume_profile": {"support": X, "resistance": Y},
                "pivot_points": {"S2": X, "S1": Y, "P": Z, "R1": A, "R2": B},
                "moving_average_confluence": "bullish_cross" | "bearish_cross" | "none",
                "atr_breakout": True/False,
                "fibonacci_levels": {"level_0": X, "level_236": Y, ...},
                "chart_signal": "STRONG_BUY" | "BUY" | "NEUTRAL" | "SELL",
                "confluence_score": 0-100
            }
        """

        try:
            # Fetch data
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)

            if hist.empty:
                return None

            # Calculate all metrics
            result = {
                "symbol": symbol,
                "timestamp": datetime.now().isoformat(),
                "price": hist['Close'].iloc[-1],
                "volume": hist['Volume'].iloc[-1]
            }

            # 1. Volume Profile (Support/Resistance)
            result["volume_profile"] = self._analyze_volume_profile(hist)

            # 2. Pivot Points (Classic)
            result["pivot_points"] = self._calculate_pivot_points(hist)

            # 3. Moving Average Confluence
            result["moving_average_confluence"] = self._analyze_ma_confluence(hist)

            # 4. ATR Breakout
            result["atr_breakout"] = self._analyze_atr_breakout(hist)

            # 5. Fibonacci Retracement
            result["fibonacci_levels"] = self._calculate_fibonacci(hist)

            # 6. Overall Chart Signal
            result["chart_signal"], result["confluence_score"] = self._calculate_chart_signal(result, hist)

            return result

        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
            return None

    def _analyze_volume_profile(self, hist, bins=20):
        """Analyze volume profile to find support/resistance"""
        try:
            # Group price data into bins and sum volume
            price_min = hist['Low'].min()
            price_max = hist['High'].max()

            bins_array = np.linspace(price_min, price_max, bins)
            hist['price_bin'] = pd.cut(hist['Close'], bins=bins_array)
            volume_by_bin = hist.groupby('price_bin')['Volume'].sum()

            # Find high volume nodes (support/resistance)
            max_volume_idx = volume_by_bin.idxmax()
            poc = (max_volume_idx.left + max_volume_idx.right) / 2  # Point of Control

            current_price = hist['Close'].iloc[-1]

            # Support below, resistance above
            support = hist[hist['Close'] < current_price]['Close'].quantile(0.25)
            resistance = hist[hist['Close'] > current_price]['Close'].quantile(0.75)

            return {
                "poc": float(poc),
                "support": float(support),
                "resistance": float(resistance),
                "current_price": float(current_price),
                "signal": "at_support" if current_price < poc else "at_resistance" if current_price > poc else "midpoint"
            }
        except:
            return None

    def _calculate_pivot_points(self, hist):
        """Calculate classic pivot points"""
        try:
            # Use last 5 days for pivot calculation
            recent = hist.tail(5)

            H = recent['High'].max()
            L = recent['Low'].min()
            C = recent['Close'].iloc[-1]

            P = (H + L + C) / 3  # Pivot
            R1 = (2 * P) - L
            R2 = P + (H - L)
            S1 = (2 * P) - H
            S2 = P - (H - L)

            current = hist['Close'].iloc[-1]

            return {
                "S2": float(S2),
                "S1": float(S1),
                "P": float(P),
                "R1": float(R1),
                "R2": float(R2),
                "current": float(current),
                "zone": self._get_pivot_zone(current, S2, S1, P, R1, R2)
            }
        except:
            return None

    def _get_pivot_zone(self, price, S2, S1, P, R1, R2):
        """Determine which pivot zone price is in"""
        if price < S2:
            return "below_S2_sell"
        elif price < S1:
            return "S2_to_S1_weak"
        elif price < P:
            return "S1_to_P_neutral"
        elif price < R1:
            return "P_to_R1_neutral"
        elif price < R2:
            return "R1_to_R2_strong"
        else:
            return "above_R2_buy"

    def _analyze_ma_confluence(self, hist):
        """Analyze moving average crossovers and confluence"""
        try:
            # Calculate moving averages
            sma_20 = hist['Close'].rolling(20).mean()
            sma_50 = hist['Close'].rolling(50).mean()
            sma_200 = hist['Close'].rolling(200).mean()

            current_price = hist['Close'].iloc[-1]
            ma_20 = sma_20.iloc[-1]
            ma_50 = sma_50.iloc[-1]
            ma_200 = sma_200.iloc[-1]

            # Price vs MAs
            above_20 = current_price > ma_20
            above_50 = current_price > ma_50
            above_200 = current_price > ma_200
            ma_20_above_50 = ma_20 > ma_50
            ma_50_above_200 = ma_50 > ma_200

            # Determine confluence
            bullish_confluence = above_20 and above_50 and above_200 and ma_20_above_50 and ma_50_above_200
            bearish_confluence = not above_20 and not above_50 and not above_200 and not ma_20_above_50 and not ma_50_above_200

            if bullish_confluence:
                signal = "strong_bullish"
            elif above_20 and above_50:
                signal = "bullish_cross"
            elif bearish_confluence:
                signal = "strong_bearish"
            elif not above_20 and not above_50:
                signal = "bearish_cross"
            else:
                signal = "none"

            return {
                "SMA_20": float(ma_20),
                "SMA_50": float(ma_50),
                "SMA_200": float(ma_200),
                "current_price": float(current_price),
                "above_20": above_20,
                "above_50": above_50,
                "above_200": above_200,
                "signal": signal,
                "confluence_strength": self._measure_confluence_strength(above_20, above_50, above_200, ma_20_above_50, ma_50_above_200)
            }
        except:
            return None

    def _measure_confluence_strength(self, above_20, above_50, above_200, ma_20_above_50, ma_50_above_200):
        """Score confluence strength 0-100"""
        score = 0
        if above_20: score += 20
        if above_50: score += 20
        if above_200: score += 20
        if ma_20_above_50: score += 20
        if ma_50_above_200: score += 20
        return score

    def _analyze_atr_breakout(self, hist, period=14, multiplier=2):
        """Check if price is breaking out beyond ATR levels"""
        try:
            high_low = hist['High'] - hist['Low']
            high_close = abs(hist['High'] - hist['Close'].shift())
            low_close = abs(hist['Low'] - hist['Close'].shift())

            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = ranges.max(axis=1)
            atr = true_range.rolling(period).mean()

            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            current_atr = atr.iloc[-1]

            price_change = abs(current_price - prev_close)
            breakout = price_change > (current_atr * multiplier * 0.5)

            return {
                "atr": float(current_atr),
                "price_change": float(price_change),
                "breakout": breakout,
                "volatility_expanded": price_change > current_atr
            }
        except:
            return None

    def _calculate_fibonacci(self, hist, lookback=52):
        """Calculate Fibonacci retracement levels"""
        try:
            recent = hist.tail(lookback)
            high = recent['High'].max()
            low = recent['Low'].min()
            diff = high - low

            current = hist['Close'].iloc[-1]

            levels = {
                "0": float(low),
                "236": float(low + diff * 0.236),
                "382": float(low + diff * 0.382),
                "500": float(low + diff * 0.500),
                "618": float(low + diff * 0.618),
                "786": float(low + diff * 0.786),
                "100": float(high),
                "current": float(current)
            }

            # Determine which level price is near
            nearest_level = self._find_nearest_fib_level(current, levels)

            return {
                **levels,
                "nearest_level": nearest_level,
                "distance_to_618": abs(current - levels["618"])
            }
        except:
            return None

    def _find_nearest_fib_level(self, price, levels):
        """Find nearest Fibonacci level"""
        distances = {k: abs(price - v) for k, v in levels.items() if k != "current"}
        return min(distances, key=distances.get)

    def _calculate_chart_signal(self, analysis, hist):
        """Combine all signals into overall chart signal"""
        try:
            score = 50  # Neutral baseline

            # Volume profile signal
            vol_profile = analysis.get("volume_profile", {})
            if vol_profile.get("signal") == "at_support":
                score += 15
            elif vol_profile.get("signal") == "at_resistance":
                score -= 15

            # Pivot points signal
            pivots = analysis.get("pivot_points", {})
            zone = pivots.get("zone", "")
            if "buy" in zone:
                score += 15
            elif "sell" in zone:
                score -= 15
            elif "strong" in zone:
                score += 10 if "buy" in zone else -10

            # MA confluence signal
            ma = analysis.get("moving_average_confluence", {})
            confluence_str = ma.get("signal", "")
            if "strong_bullish" in confluence_str:
                score += 20
            elif "bullish_cross" in confluence_str:
                score += 15
            elif "strong_bearish" in confluence_str:
                score -= 20
            elif "bearish_cross" in confluence_str:
                score -= 15

            # ATR breakout signal
            atr = analysis.get("atr_breakout", {})
            if atr.get("breakout"):
                score += 10

            # Clamp score
            score = max(0, min(100, score))

            # Determine signal
            if score >= 75:
                signal = "STRONG_BUY"
            elif score >= 60:
                signal = "BUY"
            elif score <= 25:
                signal = "STRONG_SELL"
            elif score <= 40:
                signal = "SELL"
            else:
                signal = "NEUTRAL"

            return signal, int(score)
        except:
            return "NEUTRAL", 50

    def get_chart_context_for_llama(self, symbol):
        """Format chart analysis for Llama prompt"""
        try:
            analysis = self.get_chart_analysis(symbol)
            if not analysis:
                return ""

            vp = analysis.get("volume_profile", {})
            pivots = analysis.get("pivot_points", {})
            ma = analysis.get("moving_average_confluence", {})
            atr = analysis.get("atr_breakout", {})
            fib = analysis.get("fibonacci_levels", {})

            context = f"""
ADVANCED CHART ANALYSIS:

Volume Profile:
- Support level: ${vp.get('support', 0):.2f}
- Resistance level: ${vp.get('resistance', 0):.2f}
- Point of Control: ${vp.get('poc', 0):.2f}
- Position: {vp.get('signal', 'N/A')}

Pivot Points (Classic):
- Resistance 2: ${pivots.get('R2', 0):.2f}
- Resistance 1: ${pivots.get('R1', 0):.2f}
- Pivot: ${pivots.get('P', 0):.2f}
- Support 1: ${pivots.get('S1', 0):.2f}
- Support 2: ${pivots.get('S2', 0):.2f}
- Zone: {pivots.get('zone', 'N/A')}

Moving Average Confluence:
- SMA 20: ${ma.get('SMA_20', 0):.2f}
- SMA 50: ${ma.get('SMA_50', 0):.2f}
- SMA 200: ${ma.get('SMA_200', 0):.2f}
- Signal: {ma.get('signal', 'N/A')}
- Confluence Strength: {ma.get('confluence_strength', 0)}/100

ATR Breakout:
- ATR (14): ${atr.get('atr', 0):.2f}
- Volatility Expanded: {atr.get('volatility_expanded', False)}
- Breakout: {atr.get('breakout', False)}

Fibonacci Retracement:
- Level 618 (Key): ${fib.get('618', 0):.2f}
- Nearest Level: {fib.get('nearest_level', 'N/A')}

CHART SIGNAL: {analysis.get('chart_signal', 'N/A')} (Score: {analysis.get('confluence_score', 50)}/100)
"""
            return context
        except Exception as e:
            return f"Chart analysis error: {e}"


if __name__ == "__main__":
    # Test
    analyzer = AdvancedChartAnalyzer()
    for symbol in ["INTC", "AMD", "NVDA"]:
        print(f"\n{'='*80}")
        print(f"{symbol} Advanced Chart Analysis")
        print(f"{'='*80}")
        analysis = analyzer.get_chart_analysis(symbol)
        if analysis:
            print(f"Chart Signal: {analysis.get('chart_signal')} ({analysis.get('confluence_score')}/100)")
            print(f"\nPrompt Context:\n{analyzer.get_chart_context_for_llama(symbol)}")
