#!/usr/bin/env python3
"""
Stability Test: Larger Pool + 6 Months + Multiple Cycles
Tests robustness across different market conditions and symbol counts
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate all indicators needed for hybrid strategy"""
    df = df.copy()

    # Donchian Channels
    df['High_20'] = df['High'].shift(1).rolling(window=20).max()
    df['Low_10'] = df['Low'].shift(1).rolling(window=10).min()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()

    # ATR for scale-outs
    tr1 = df['High'] - df['Low']
    tr2 = (df['High'] - df['Close'].shift(1)).abs()
    tr3 = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    # Bollinger Bands for squeeze
    df['SMA_BB'] = df['Close'].rolling(20).mean()
    df['STD_BB'] = df['Close'].rolling(20).std()
    df['BB_Width'] = (2 * df['STD_BB'] * 2) / df['SMA_BB'] * 100

    # 2-period RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=2).mean()
    rs = gain / (loss + 1e-9)
    df['RSI_2'] = 100 - (100 / (1 + rs))

    # ADX 14
    up_move = df['High'].diff()
    down_move = -df['Low'].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    atr14 = df['ATR']
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(14).mean() / atr14)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(14).mean() / atr14)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    df['ADX'] = dx.rolling(14).mean()

    return df

def run_backtest_period(symbol, start_date, end_date):
    """Run backtest for one symbol over a specific period"""
    try:
        hist = yf.download(symbol, start=start_date, end=end_date, progress=False)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)

        if len(hist) < 50:
            return None

        df = calculate_indicators(hist).dropna().copy()

        # Track positions
        positions = np.zeros(len(df))
        pos_state = 0
        trades = []

        close = df['Close'].values
        high_20 = df['High_20'].values
        low_10 = df['Low_10'].values
        adx = df['ADX'].values
        rsi2 = df['RSI_2'].values
        sma20 = df['SMA_20'].values
        bb_width = df['BB_Width'].values

        bb_20th = np.nanpercentile(bb_width[~np.isnan(bb_width)], 20)

        for i in range(50, len(df)):
            current_adx = adx[i]
            current_bb = bb_width[i]

            # Entry
            if pos_state == 0:
                if current_bb > bb_20th:
                    continue

                if current_adx >= 25 and close[i] > high_20[i]:
                    pos_state = 1
                    entry_price = close[i]
                    entry_idx = i
                elif current_adx < 20 and rsi2[i] < 20:
                    pos_state = 2
                    entry_price = close[i]
                    entry_idx = i

            # Exit
            elif pos_state > 0:
                if close[i] < entry_price * (1 - 0.045):
                    pnl = (close[i] - entry_price) / entry_price
                    trades.append({'pnl': pnl, 'win': 1 if pnl > 0 else 0, 'exit': 'stop'})
                    pos_state = 0
                elif close[i] >= entry_price * 1.10:
                    pnl = (close[i] - entry_price) / entry_price
                    trades.append({'pnl': pnl, 'win': 1 if pnl > 0 else 0, 'exit': 'profit'})
                    pos_state = 0
                elif (i - entry_idx) > 20:
                    pnl = (close[i] - entry_price) / entry_price
                    trades.append({'pnl': pnl, 'win': 1 if pnl > 0 else 0, 'exit': 'time'})
                    pos_state = 0

            positions[i] = 1 if pos_state > 0 else 0

        return {
            'symbol': symbol,
            'trades': trades,
            'num_trades': len(trades),
            'win_rate': np.mean([t['win'] for t in trades]) * 100 if trades else 0,
            'total_pnl': np.sum([t['pnl'] for t in trades]) * 100 if trades else 0,
            'avg_pnl': np.mean([t['pnl'] for t in trades]) * 100 if trades else 0
        }

    except Exception as e:
        return None

def test_stability(symbols, pool_size=25):
    """Test stability with different pool sizes and periods"""
    print("\n" + "="*120)
    print("STABILITY TEST: Larger Pool + 6 Months + Multiple Cycles")
    print("="*120)

    # Test periods (6-month windows)
    test_periods = [
        ("2026-02-01", "2026-08-01", "Feb-Aug 2026 (Recent)"),
        ("2025-08-01", "2026-02-01", "Aug 2025-Feb 2026 (Winter)"),
        ("2025-02-01", "2025-08-01", "Feb-Aug 2025 (Summer)"),
    ]

    all_results = []

    for start, end, label in test_periods:
        print(f"\n{'='*120}")
        print(f"PERIOD: {label} ({start} to {end})")
        print(f"{'='*120}")

        period_results = []
        success_count = 0

        for i, symbol in enumerate(symbols[:pool_size], 1):
            print(f"  [{i:2d}/{pool_size}] {symbol:6} ... ", end="", flush=True)

            result = run_backtest_period(symbol, start, end)

            if result and result['num_trades'] > 0:
                period_results.append(result)
                success_count += 1
                print(f"✅ {result['num_trades']:3d} trades | WR: {result['win_rate']:5.1f}% | P&L: {result['total_pnl']:+6.2f}%")
            else:
                print(f"❌ No trades or data error")

            time.sleep(0.1)  # Rate limiting

        # Calculate period stats
        if period_results:
            total_trades = sum(r['num_trades'] for r in period_results)
            avg_win_rate = np.mean([r['win_rate'] for r in period_results])
            total_pnl = sum(r['total_pnl'] for r in period_results)
            avg_pnl = np.mean([r['avg_pnl'] for r in period_results])
            sharpe = avg_pnl / (np.std([r['avg_pnl'] for r in period_results]) + 1e-9) * np.sqrt(252)

            all_results.append({
                'period': label,
                'symbols': success_count,
                'total_trades': total_trades,
                'avg_win_rate': avg_win_rate,
                'total_pnl': total_pnl,
                'avg_pnl_per_symbol': total_pnl / success_count,
                'sharpe': sharpe
            })

            print(f"\n  📊 Period Summary:")
            print(f"     Successful symbols: {success_count}/{pool_size}")
            print(f"     Total trades: {total_trades}")
            print(f"     Avg win rate: {avg_win_rate:.1f}%")
            print(f"     Total P&L: {total_pnl:+.2f}%")
            print(f"     Avg P&L per symbol: {total_pnl / success_count:+.2f}%")
            print(f"     Sharpe ratio: {sharpe:.2f}")

    # Cross-period comparison
    print(f"\n\n{'='*120}")
    print("STABILITY ANALYSIS: CROSS-PERIOD COMPARISON")
    print(f"{'='*120}\n")

    if all_results:
        df_results = pd.DataFrame(all_results)

        print(f"{'Period':<25} {'Symbols':<10} {'Trades':<10} {'Win Rate':<12} {'Total P&L':<12} {'Sharpe':<10}")
        print("-" * 120)
        for _, row in df_results.iterrows():
            print(f"{row['period']:<25} {row['symbols']:<10} {row['total_trades']:<10} "
                  f"{row['avg_win_rate']:>10.1f}% {row['total_pnl']:>10.2f}% {row['sharpe']:>9.2f}")

        # Variance analysis
        print(f"\n{'='*120}")
        print("VARIANCE ANALYSIS (Stability Metrics)")
        print(f"{'='*120}\n")

        win_rates = df_results['avg_win_rate'].values
        sharpe_ratios = df_results['sharpe'].values
        pnl_totals = df_results['total_pnl'].values

        print(f"Win Rate:")
        print(f"  Mean:   {np.mean(win_rates):.1f}%")
        print(f"  StdDev: {np.std(win_rates):.1f}%")
        print(f"  Range:  {np.min(win_rates):.1f}% - {np.max(win_rates):.1f}%")
        print(f"  Coefficient of Variation: {np.std(win_rates) / np.mean(win_rates) * 100:.1f}%")

        print(f"\nTotal P&L:")
        print(f"  Mean:   {np.mean(pnl_totals):.2f}%")
        print(f"  StdDev: {np.std(pnl_totals):.2f}%")
        print(f"  Range:  {np.min(pnl_totals):.2f}% - {np.max(pnl_totals):.2f}%")

        print(f"\nSharpe Ratio:")
        print(f"  Mean:   {np.mean(sharpe_ratios):.2f}")
        print(f"  StdDev: {np.std(sharpe_ratios):.2f}")
        print(f"  Range:  {np.min(sharpe_ratios):.2f} - {np.max(sharpe_ratios):.2f}")

        # Stability verdict
        cv = np.std(win_rates) / np.mean(win_rates)
        print(f"\n{'='*120}")
        print("STABILITY VERDICT")
        print(f"{'='*120}\n")

        if cv < 0.10:
            print("✅ HIGHLY STABLE: Win rate variance < 10% across periods")
        elif cv < 0.20:
            print("✅ STABLE: Win rate variance 10-20% across periods")
        elif cv < 0.30:
            print("⚠️  MODERATE: Win rate variance 20-30% (acceptable for live)")
        else:
            print("❌ UNSTABLE: Win rate variance > 30% (higher risk)")

        print(f"\nPredicted Live Performance (Aug 26 - Sep 2026):")
        print(f"  Expected Win Rate: {np.mean(win_rates):.1f}% ± {np.std(win_rates):.1f}%")
        print(f"  Expected Monthly P&L: {np.mean(pnl_totals) / 3:.2f}%")
        print(f"  Expected Sharpe Ratio: {np.mean(sharpe_ratios):.2f}")
        print(f"  Confidence Level: {'HIGH' if cv < 0.20 else 'MODERATE' if cv < 0.30 else 'LOW'}")


# ========================================
# RUN STABILITY TEST
# ========================================
if __name__ == "__main__":
    # Larger pool: Top 50 NASDAQ + S&P 500 leaders
    symbols = [
        # FAANG+ (must-haves)
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "NFLX",

        # Mega-cap tech
        "AVGO", "BROADCOM", "QCOM", "AMD", "INTC", "ASML", "CRM", "ADBE",

        # Semi/Chip leaders
        "LRCX", "ASML", "KLAC", "MU", "SNPS", "CDNS", "MCHP", "NXPI",

        # Cloud/SaaS
        "SALESFORCE", "OKTA", "CRWD", "ZS", "DDOG", "NET", "PSTG", "SNOW",

        # Fintech/Finance
        "PYPL", "SQ", "UPST", "COIN", "SCHW", "VIRT", "HOOD", "IBKR",

        # Healthcare/Biotech
        "JNJ", "UNH", "PFE", "ABBV", "LLY", "MRK", "AMGN", "GILD",

        # Energy/Industrials
        "XOM", "CVX", "CAT", "RTX", "LMT", "BA", "HON", "MMM",

        # Retail/Consumer
        "AMZN", "TSLA", "MCD", "NKE", "COST", "WMT", "HD", "LOW"
    ]

    # Remove duplicates and take top 50
    symbols = list(dict.fromkeys(symbols))[:50]

    # Run stability test with 25 symbols, 6-month windows
    test_stability(symbols, pool_size=25)
