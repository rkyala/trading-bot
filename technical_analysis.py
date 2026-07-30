#!/usr/bin/env python3
"""
Technical analysis indicators for mean-reversion confirmation.
Provides VWAP, RSI, Fibonacci levels, and overbought scoring.
"""
import yfinance as yf
import pandas as pd
import numpy as np
import logging

log = logging.getLogger(__name__)

def get_ohlcv_data(symbol, period_days=30):
    """Fetch OHLCV data for technical analysis."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1mo")
        if hist.empty or len(hist) < 14:
            return None
        return hist
    except Exception as e:
        log.debug(f"Error fetching OHLCV for {symbol}: {e}")
        return None

def calculate_vwap(df):
    """Calculate Volume Weighted Average Price."""
    if df is None or len(df) < 5:
        return None
    try:
        typical_price = (df['High'] + df['Low'] + df['Close']) / 3
        vwap = (typical_price * df['Volume']).rolling(20).sum() / df['Volume'].rolling(20).sum()
        return float(vwap.iloc[-1])
    except Exception as e:
        log.debug(f"Error calculating VWAP: {e}")
        return None

def calculate_rsi(df, period=14):
    """Calculate Relative Strength Index."""
    if df is None or len(df) < period:
        return None
    try:
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except Exception as e:
        log.debug(f"Error calculating RSI: {e}")
        return None

def calculate_fibonacci_levels(df, lookback=20):
    """Calculate Fibonacci retracement levels from recent swing."""
    if df is None or len(df) < lookback:
        return None
    try:
        recent = df.tail(lookback)
        high = recent['High'].max()
        low = recent['Low'].min()
        diff = high - low

        levels = {
            '23.6': high - (diff * 0.236),
            '38.2': high - (diff * 0.382),
            '50.0': high - (diff * 0.500),
            '61.8': high - (diff * 0.618),
        }
        return {k: float(v) for k, v in levels.items()}
    except Exception as e:
        log.debug(f"Error calculating Fibonacci: {e}")
        return None

def calculate_moving_average(df, period=20):
    """Calculate simple moving average."""
    if df is None or len(df) < period:
        return None
    try:
        sma = df['Close'].rolling(period).mean()
        return float(sma.iloc[-1])
    except Exception as e:
        log.debug(f"Error calculating MA: {e}")
        return None

def score_technical_setup(symbol, current_price, spike_pct, df=None):
    """
    Score how overbought/extended a stock is.
    Returns dict with score (0-100), indicators, and reasoning.
    """
    result = {
        'symbol': symbol,
        'score': 0,
        'current_price': current_price,
        'spike_pct': spike_pct,
        'vwap': None,
        'rsi': None,
        'sma_20': None,
        'fib_levels': None,
        'reasoning': []
    }

    if df is None:
        df = get_ohlcv_data(symbol)

    if df is None:
        return result

    # Calculate technicals
    vwap = calculate_vwap(df)
    rsi = calculate_rsi(df)
    sma_20 = calculate_moving_average(df, 20)
    fib = calculate_fibonacci_levels(df)

    result['vwap'] = vwap
    result['rsi'] = rsi
    result['sma_20'] = sma_20
    result['fib_levels'] = fib

    # Score VWAP extension (price above VWAP = overbought)
    if vwap and current_price > vwap:
        extension_pct = (current_price - vwap) / vwap * 100
        if extension_pct > 3:
            result['score'] += 25
            result['reasoning'].append(f"Extended +{extension_pct:.1f}% above VWAP")
        elif extension_pct > 1.5:
            result['score'] += 15
            result['reasoning'].append(f"Extended +{extension_pct:.1f}% above VWAP")
    elif vwap:
        result['reasoning'].append(f"Price below VWAP (not extended)")

    # Score RSI (> 70 = overbought)
    if rsi:
        if rsi > 75:
            result['score'] += 25
            result['reasoning'].append(f"RSI {rsi:.0f} (extremely overbought)")
        elif rsi > 70:
            result['score'] += 20
            result['reasoning'].append(f"RSI {rsi:.0f} (overbought)")
        elif rsi > 65:
            result['score'] += 10
            result['reasoning'].append(f"RSI {rsi:.0f} (extended)")
        else:
            result['reasoning'].append(f"RSI {rsi:.0f} (neutral)")

    # Score spike magnitude
    if spike_pct > 8:
        result['score'] += 20
        result['reasoning'].append(f"Large spike +{spike_pct:.1f}%")
    elif spike_pct > 6:
        result['score'] += 15
        result['reasoning'].append(f"Good spike +{spike_pct:.1f}%")
    elif spike_pct > 5:
        result['score'] += 10
        result['reasoning'].append(f"Solid spike +{spike_pct:.1f}%")

    # Price vs SMA (above SMA = uptrend)
    if sma_20 and current_price > sma_20:
        sma_above_pct = (current_price - sma_20) / sma_20 * 100
        if sma_above_pct > 5:
            result['score'] += 10
            result['reasoning'].append(f"Trading {sma_above_pct:.1f}% above 20-SMA (strong uptrend)")
        else:
            result['reasoning'].append(f"Slightly above 20-SMA (+{sma_above_pct:.1f}%)")
    elif sma_20:
        result['reasoning'].append(f"Below 20-SMA (no uptrend)")

    # Cap at 100
    result['score'] = min(result['score'], 100)

    return result

def format_technical_for_claude(candidates):
    """Format technical data for Stage 2 analysis by Claude."""
    formatted = []
    for cand in candidates:
        tech = cand.get('technical', {})

        text = f"{cand['symbol']}: +{cand.get('pct_change', 0):.1f}% | Score: {tech.get('score', 0)}"

        if tech.get('rsi'):
            text += f" | RSI: {tech['rsi']:.0f}"

        if tech.get('vwap') and cand.get('price'):
            ext_pct = (cand.get('price', 0) - tech['vwap']) / tech['vwap'] * 100 if tech['vwap'] else 0
            text += f" | VWAP: {ext_pct:+.1f}%"

        if tech.get('fib_levels'):
            fibs = tech['fib_levels']
            text += f" | Fib support at: 38.2% ${fibs['38.2']:.2f}"

        reasoning = tech.get('reasoning', [])
        if reasoning:
            text += f" | {' | '.join(reasoning[:2])}"

        formatted.append(text)

    return "\n".join(formatted)
