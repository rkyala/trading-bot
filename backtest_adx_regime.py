#!/usr/bin/env python3
"""
Vectorized Backtest: Pure Breakout vs ADX Regime-Switching
Production-grade backtest with proper ADX calculation and performance metrics
"""

import yfinance as yf
import pandas as pd
import numpy as np

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1. Donchian Breakout Channels
    df['High_20'] = df['High'].shift(1).rolling(window=20).max()
    df['Low_10'] = df['Low'].shift(1).rolling(window=10).min()

    # 2. Mean Reversion Indicators
    df['SMA_20'] = df['Close'].rolling(window=20).mean()

    # 2-period RSI for Mean Reversion
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=2).mean()
    rs = gain / (loss + 1e-9)
    df['RSI_2'] = 100 - (100 / (1 + rs))

    # 3. Average Directional Index (ADX 14) for Regime Detection
    up_move = df['High'].diff()
    down_move = -df['Low'].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    # True Range
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift(1)).abs()
    tr3 = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr14 = tr.rolling(14).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr14)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr14)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    df['ADX'] = dx.rolling(14).mean()

    return df

def run_backtest(ticker: str, start_date: str = "2022-01-01", end_date: str = "2026-08-20"):
    print(f"\n{'='*100}")
    print(f"BACKTEST: {ticker} | {start_date} to {end_date}")
    print(f"{'='*100}")

    # Download Historical Data
    print(f"Downloading {ticker}...", end=" ", flush=True)
    raw = yf.download(ticker, start=start_date, end=end_date, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    print("✅")
    print(f"Calculating indicators...", end=" ", flush=True)
    df = calculate_indicators(raw).dropna().copy()
    print(f"✅ ({len(df)} bars)")

    # Track Positions (1 = Long, 0 = Flat)
    pure_breakout_pos = np.zeros(len(df))
    regime_switch_pos = np.zeros(len(df))

    pb_state = 0
    rs_state = 0

    close = df['Close'].values
    high_20 = df['High_20'].values
    low_10 = df['Low_10'].values
    adx = df['ADX'].values
    rsi2 = df['RSI_2'].values
    sma20 = df['SMA_20'].values

    print(f"Running backtest...", end=" ", flush=True)

    for i in range(1, len(df)):
        # --- 1. PURE BREAKOUT LOGIC ---
        if pb_state == 0 and close[i] > high_20[i]:
            pb_state = 1  # Enter Long
        elif pb_state == 1 and close[i] < low_10[i]:
            pb_state = 0  # Exit
        pure_breakout_pos[i] = pb_state

        # --- 2. REGIME-SWITCHING LOGIC ---
        current_adx = adx[i]

        if rs_state == 0:
            # Entry Conditions
            if current_adx >= 25 and close[i] > high_20[i]:
                rs_state = 1  # Enter Breakout in Trend Regime
            elif current_adx < 20 and rsi2[i] < 20:
                rs_state = 2  # Enter Mean Reversion in Range Regime

        elif rs_state == 1:  # Active Breakout Position
            if close[i] < low_10[i]:
                rs_state = 0  # Exit Breakout

        elif rs_state == 2:  # Active Mean Reversion Position
            if close[i] >= sma20[i]:
                rs_state = 0  # Exit Mean Reversion Target Reached

        regime_switch_pos[i] = 1 if rs_state > 0 else 0

    print("✅")

    # Calculate Returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Pure_Breakout_Returns'] = df['Market_Returns'] * pd.Series(pure_breakout_pos, index=df.index).shift(1)
    df['Regime_Switch_Returns'] = df['Market_Returns'] * pd.Series(regime_switch_pos, index=df.index).shift(1)

    # Performance Metrics
    def get_stats(returns):
        returns = returns.dropna()
        cum_ret = (1 + returns).cumprod().iloc[-1] - 1
        ann_ret = (1 + returns.mean()) ** 252 - 1
        sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252)
        cum_series = (1 + returns).cumprod()
        drawdown = (cum_series - cum_series.cummax()) / cum_series.cummax()
        max_dd = drawdown.min()
        win_rate = (returns > 0).sum() / len(returns) * 100
        return cum_ret, ann_ret, sharpe, max_dd, win_rate

    pb_cum, pb_ann, pb_sharpe, pb_dd, pb_wr = get_stats(df['Pure_Breakout_Returns'])
    rs_cum, rs_ann, rs_sharpe, rs_dd, rs_wr = get_stats(df['Regime_Switch_Returns'])
    bh_cum, bh_ann, bh_sharpe, bh_dd, bh_wr = get_stats(df['Market_Returns'])

    # Format Results Output
    summary = pd.DataFrame({
        "Metric": ["Total Return", "Annual Return", "Sharpe Ratio", "Max Drawdown", "Win Rate"],
        "Buy & Hold": [f"{bh_cum*100:+.2f}%", f"{bh_ann*100:+.2f}%", f"{bh_sharpe:.2f}", f"{bh_dd*100:.2f}%", f"{bh_wr:.1f}%"],
        "Pure Breakout": [f"{pb_cum*100:+.2f}%", f"{pb_ann*100:+.2f}%", f"{pb_sharpe:.2f}", f"{pb_dd*100:.2f}%", f"{pb_wr:.1f}%"],
        "Regime-Switch (ADX)": [f"{rs_cum*100:+.2f}%", f"{rs_ann*100:+.2f}%", f"{rs_sharpe:.2f}", f"{rs_dd*100:.2f}%", f"{rs_wr:.1f}%"]
    })

    print("\n" + summary.to_string(index=False))

    # Comparison
    print(f"\n{'='*100}")
    print("REGIME-SWITCHING vs PURE BREAKOUT:")
    print(f"{'='*100}")
    print(f"  Return Improvement: {(rs_cum - pb_cum)*100:+.2f}% ({rs_cum*100:.2f}% vs {pb_cum*100:.2f}%)")
    print(f"  Sharpe Improvement: {rs_sharpe - pb_sharpe:+.2f} ({rs_sharpe:.2f} vs {pb_sharpe:.2f})")
    print(f"  Drawdown Reduction: {(rs_dd - pb_dd)*100:.2f}% ({rs_dd*100:.2f}% vs {pb_dd*100:.2f}%)")
    print(f"  Win Rate Delta: {rs_wr - pb_wr:+.1f}% ({rs_wr:.1f}% vs {pb_wr:.1f}%)")

    return {
        'ticker': ticker,
        'bh': {'return': bh_cum, 'sharpe': bh_sharpe, 'dd': bh_dd, 'wr': bh_wr},
        'pb': {'return': pb_cum, 'sharpe': pb_sharpe, 'dd': pb_dd, 'wr': pb_wr},
        'rs': {'return': rs_cum, 'sharpe': rs_sharpe, 'dd': rs_dd, 'wr': rs_wr}
    }

# Run on multiple symbols
if __name__ == "__main__":
    symbols = ["QQQ", "SPY", "NVDA", "TSLA"]

    print("\n" + "="*100)
    print("VECTORIZED BACKTEST: ADX REGIME-SWITCHING vs PURE BREAKOUT")
    print("="*100)

    results = []
    for symbol in symbols:
        try:
            result = run_backtest(symbol)
            results.append(result)
        except Exception as e:
            print(f"❌ Error with {symbol}: {e}")

    # Summary table
    print("\n" + "="*100)
    print("SUMMARY: ALL SYMBOLS")
    print("="*100)

    summary_data = []
    for r in results:
        summary_data.append({
            'Symbol': r['ticker'],
            'Pure BO Return': f"{r['pb']['return']*100:+.2f}%",
            'Pure BO Sharpe': f"{r['pb']['sharpe']:.2f}",
            'Regime-Switch Return': f"{r['rs']['return']*100:+.2f}%",
            'Regime-Switch Sharpe': f"{r['rs']['sharpe']:.2f}",
            'Improvement': f"{(r['rs']['return'] - r['pb']['return'])*100:+.2f}%"
        })

    summary_df = pd.DataFrame(summary_data)
    print(summary_df.to_string(index=False))

    print("\n✅ Backtest complete!")
