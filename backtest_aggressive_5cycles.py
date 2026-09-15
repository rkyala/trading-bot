#!/usr/bin/env python3
"""
Aggressive Backtest: 5-Cycle Regime-Aware Position Sizing Optimization
Tests 5 different allocation/stop-loss configurations to find optimal regime-switching strategy
"""

import yfinance as yf
import pandas as pd
import numpy as np

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Donchian Channels
    df['High_20'] = df['High'].shift(1).rolling(window=20).max()
    df['Low_10'] = df['Low'].shift(1).rolling(window=10).min()
    df['SMA_20'] = df['Close'].rolling(window=20).mean()

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

def run_cycle(ticker, cycle_config, start_date="2022-01-01", end_date="2026-08-20"):
    """Run one backtest cycle with specific position sizing config"""

    # Download and calculate
    raw = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = calculate_indicators(raw).dropna().copy()

    # Extract config
    trend_size = cycle_config['trend_size']
    range_size = cycle_config['range_size']
    trans_size = cycle_config['trans_size']
    trend_sl = cycle_config['trend_sl']
    range_sl = cycle_config['range_sl']
    name = cycle_config['name']

    # Position tracking
    positions = np.zeros(len(df))
    pos_state = 0
    pos_size = 1.0
    entry_price = 0
    entry_sl = -0.05

    close = df['Close'].values
    high_20 = df['High_20'].values
    low_10 = df['Low_10'].values
    adx = df['ADX'].values
    rsi2 = df['RSI_2'].values
    sma20 = df['SMA_20'].values

    for i in range(1, len(df)):
        current_adx = adx[i]

        # Determine regime and position size
        if current_adx >= 25:
            regime = "TREND"
            pos_size = trend_size
            entry_sl = trend_sl
        elif current_adx < 20:
            regime = "RANGE"
            pos_size = range_size
            entry_sl = range_sl
        else:
            regime = "TRANS"
            pos_size = trans_size
            entry_sl = (trend_sl + range_sl) / 2

        # Entry Logic
        if pos_state == 0:
            if current_adx >= 25 and close[i] > high_20[i]:
                pos_state = 1
                entry_price = close[i]
            elif current_adx < 20 and rsi2[i] < 20:
                pos_state = 2
                entry_price = close[i]

        # Exit Logic
        elif pos_state == 1:  # Trend breakout
            if close[i] < low_10[i] or close[i] < entry_price * (1 + entry_sl):
                pos_state = 0
        elif pos_state == 2:  # Range mean-reversion
            if close[i] >= sma20[i] or close[i] < entry_price * (1 + entry_sl):
                pos_state = 0

        positions[i] = pos_size if pos_state > 0 else 0

    # Calculate returns
    df['Market_Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = df['Market_Returns'] * pd.Series(positions, index=df.index).shift(1)

    # Stats
    returns = df['Strategy_Returns'].dropna()
    cum_ret = (1 + returns).cumprod().iloc[-1] - 1
    ann_ret = (1 + returns.mean()) ** 252 - 1
    sharpe = (returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252)
    cum_series = (1 + returns).cumprod()
    drawdown = (cum_series - cum_series.cummax()) / cum_series.cummax()
    max_dd = drawdown.min()
    win_rate = (returns > 0).sum() / len(returns) * 100

    return {
        'name': name,
        'ticker': ticker,
        'total_return': cum_ret,
        'annual_return': ann_ret,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'num_trades': (positions != 0).sum()
    }

# Define 5 cycles of aggressive testing
CYCLES = [
    {
        'name': 'CYCLE 1: Conservative Sizing',
        'trend_size': 1.0,
        'range_size': 0.50,
        'trans_size': 0.75,
        'trend_sl': -0.03,
        'range_sl': -0.015
    },
    {
        'name': 'CYCLE 2: Aggressive Trending',
        'trend_size': 1.30,
        'range_size': 0.30,
        'trans_size': 0.60,
        'trend_sl': -0.05,
        'range_sl': -0.01
    },
    {
        'name': 'CYCLE 3: Balanced with Wide Stops',
        'trend_size': 1.00,
        'range_size': 0.60,
        'trans_size': 0.80,
        'trend_sl': -0.04,
        'range_sl': -0.02
    },
    {
        'name': 'CYCLE 4: Extreme Regime Weighting',
        'trend_size': 1.50,
        'range_size': 0.20,
        'trans_size': 0.70,
        'trend_sl': -0.06,
        'range_sl': -0.008
    },
    {
        'name': 'CYCLE 5: Tight Risk Management',
        'trend_size': 0.80,
        'range_size': 0.70,
        'trans_size': 0.75,
        'trend_sl': -0.025,
        'range_sl': -0.018
    }
]

if __name__ == "__main__":
    symbols = ["NVDA", "TSLA", "QQQ"]

    print("\n" + "="*140)
    print("AGGRESSIVE 5-CYCLE BACKTEST: REGIME-AWARE POSITION SIZING")
    print("="*140)
    print("Testing 5 different position sizing + stop-loss combinations on 3 stocks\n")

    all_results = {}

    for cycle_num, cycle_config in enumerate(CYCLES, 1):
        print(f"\n{'='*140}")
        print(f"{cycle_config['name']}")
        print(f"{'='*140}")
        print(f"  Trend Mode: {cycle_config['trend_size']:.2f}x size, {cycle_config['trend_sl']*100:+.1f}% stop")
        print(f"  Range Mode: {cycle_config['range_size']:.2f}x size, {cycle_config['range_sl']*100:+.1f}% stop")
        print(f"  Transition: {cycle_config['trans_size']:.2f}x size")
        print()

        cycle_results = []

        for symbol in symbols:
            print(f"  {symbol}...", end=" ", flush=True)
            try:
                result = run_cycle(symbol, cycle_config)
                cycle_results.append(result)
                print(f"✅ Return: {result['total_return']*100:+.2f}% | Sharpe: {result['sharpe']:.2f} | DD: {result['max_dd']*100:.2f}%")
            except Exception as e:
                print(f"❌ {e}")

        # Summary for cycle
        if cycle_results:
            avg_return = np.mean([r['total_return'] for r in cycle_results])
            avg_sharpe = np.mean([r['sharpe'] for r in cycle_results])
            avg_dd = np.mean([r['max_dd'] for r in cycle_results])

            all_results[cycle_num] = {
                'name': cycle_config['name'],
                'avg_return': avg_return,
                'avg_sharpe': avg_sharpe,
                'avg_dd': avg_dd,
                'results': cycle_results
            }

            print(f"\n  📊 Cycle Average: Return {avg_return*100:+.2f}% | Sharpe {avg_sharpe:.2f} | Drawdown {avg_dd*100:.2f}%")

    # Find winner
    print("\n" + "="*140)
    print("🏆 CYCLE PERFORMANCE RANKING")
    print("="*140)

    ranked = sorted(all_results.items(), key=lambda x: x[1]['avg_sharpe'], reverse=True)

    for rank, (cycle_num, data) in enumerate(ranked, 1):
        print(f"\n  #{rank} - {data['name']}")
        print(f"      Average Return:  {data['avg_return']*100:+.2f}%")
        print(f"      Average Sharpe:  {data['avg_sharpe']:.2f}")
        print(f"      Average Drawdown: {data['avg_dd']*100:.2f}%")

        for result in data['results']:
            print(f"        • {result['ticker']}: {result['total_return']*100:+.2f}% (Sharpe: {result['sharpe']:.2f}, WR: {result['win_rate']:.1f}%)")

    # Recommendation
    winner = ranked[0]
    print("\n" + "="*140)
    print("✅ RECOMMENDED CONFIGURATION")
    print("="*140)
    print(f"\n{winner[1]['name']}")
    print(f"  → Best risk-adjusted returns across all symbols")
    print(f"  → Sharpe Ratio: {winner[1]['avg_sharpe']:.2f}")
    print(f"  → Max Drawdown: {winner[1]['avg_dd']*100:.2f}%")
    print(f"  → Deploy to bot immediately for live trading")
    print()
