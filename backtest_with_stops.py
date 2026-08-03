#!/usr/bin/env python3
"""
Backtest mean-reversion strategy with profit targets AND stop loss.

Exit orders per position:
- 50% @ +0.75% (quick profit)
- 50% @ +2.0% (full target)
- STOP LOSS @ -0.5% (risk limit, cancels all others)

Tests which exit fills first and overall P&L.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Configuration
SYMBOLS = ["META", "GOOGL", "MSFT", "BA", "AMZN"]
LOOKBACK_DAYS = 30
ENTRY_CONFIDENCE = 0.55  # Only backtest high-confidence trades
BUY_SIZE = 200  # $ per position
TOTAL_BUDGET = 2000

# Exit targets
EXIT_1_PCT = 0.0075   # 50% @ +0.75%
EXIT_2_PCT = 0.02     # 50% @ +2%
STOP_LOSS_PCT = -0.005  # Stop @ -0.5%

def get_historical_data(symbol, days=LOOKBACK_DAYS):
    """Fetch historical price data."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    df = yf.download(symbol, start=start_date, end=end_date, progress=False)
    return df

def simulate_mean_reversion_entry(df, symbol):
    """
    Find pullback opportunities:
    - Stock spiked 5-8% intraday
    - Then pulled back 1-4%
    Returns: list of (date, entry_price, spike_pct, pullback_pct)
    """
    entries = []

    for i in range(1, len(df)):
        prev_close = float(df['Close'].iloc[i-1])
        curr_high = float(df['High'].iloc[i])
        curr_low = float(df['Low'].iloc[i])
        curr_close = float(df['Close'].iloc[i])

        # Spike: high vs previous close
        spike_pct = (curr_high - prev_close) / prev_close

        # Pullback: low vs high
        pullback_pct = (curr_low - curr_high) / curr_high

        # Entry condition: spiked 5-8%, pulled back 1-4%
        if 0.05 <= spike_pct <= 0.08 and -0.04 <= pullback_pct <= -0.01:
            entry_price = curr_low  # Buy at pullback low
            entries.append({
                'date': df.index[i],
                'entry_price': entry_price,
                'spike_pct': spike_pct,
                'pullback_pct': pullback_pct
            })

    return entries

def simulate_exit_fills(df, entry_date, entry_price, symbol):
    """
    Simulate exit fills after entry.
    Returns: (exit_type, exit_price, exit_date, pnl_pct)

    exit_type: 'exit_1' (50% @ +0.75%), 'exit_2' (50% @ +2%), 'stop_loss' (-0.5%)
    """
    entry_idx = df.index.get_loc(entry_date)

    # Exit prices
    exit_1_price = entry_price * (1 + EXIT_1_PCT)
    exit_2_price = entry_price * (1 + EXIT_2_PCT)
    stop_loss_price = entry_price * (1 + STOP_LOSS_PCT)

    # Look forward up to 5 days for exit
    for i in range(entry_idx + 1, min(entry_idx + 6, len(df))):
        high = float(df['High'].iloc[i])
        low = float(df['Low'].iloc[i])
        close = float(df['Close'].iloc[i])
        exit_date = df.index[i]

        # Check which exit triggers first (order matters)
        if low <= stop_loss_price:
            # Stop loss hit first
            return {
                'type': 'stop_loss',
                'price': stop_loss_price,
                'date': exit_date,
                'pnl_pct': STOP_LOSS_PCT
            }

        if high >= exit_1_price:
            # First profit target hit (this fills 50%)
            return {
                'type': 'exit_1',
                'price': exit_1_price,
                'date': exit_date,
                'pnl_pct': EXIT_1_PCT
            }

        if high >= exit_2_price:
            # Second profit target hit (this fills remaining 50%)
            return {
                'type': 'exit_2',
                'price': exit_2_price,
                'date': exit_date,
                'pnl_pct': EXIT_2_PCT
            }

    # No exit in 5 days, use day 5 close
    if entry_idx + 5 < len(df):
        return {
            'type': 'timeout',
            'price': df['Close'].iloc[entry_idx + 5],
            'date': df.index[entry_idx + 5],
            'pnl_pct': (df['Close'].iloc[entry_idx + 5] - entry_price) / entry_price
        }

    return None

def run_backtest():
    """Run full backtest."""
    all_trades = []
    total_invested = 0
    total_profit = 0

    for symbol in SYMBOLS:
        print(f"\n{'='*60}")
        print(f"  {symbol}")
        print(f"{'='*60}")

        df = get_historical_data(symbol)
        if df.empty:
            print(f"  No data for {symbol}")
            continue

        entries = simulate_mean_reversion_entry(df, symbol)
        print(f"  Found {len(entries)} pullback opportunities")

        symbol_profit = 0
        symbol_trades = 0

        for entry in entries:
            if total_invested >= TOTAL_BUDGET * 0.8:  # Don't exceed budget
                break

            entry_price = entry['entry_price']
            exit_info = simulate_exit_fills(df, entry['date'], entry_price, symbol)

            if not exit_info:
                continue

            # Calculate P&L for this trade
            # Strategy: 50% exits at +0.75%, 50% at +2%, or stop loss at -0.5%
            if exit_info['type'] == 'exit_1':
                # 50% exits at +0.75%, 50% stays (assume sells at next open, ~+0.5%)
                trade_pnl_pct = (EXIT_1_PCT * 0.5) + (0.005 * 0.5)  # Average
            elif exit_info['type'] == 'exit_2':
                # Both exit targets hit in sequence
                trade_pnl_pct = EXIT_1_PCT * 0.5 + EXIT_2_PCT * 0.5  # Blended
            elif exit_info['type'] == 'stop_loss':
                trade_pnl_pct = STOP_LOSS_PCT
            else:
                trade_pnl_pct = exit_info['pnl_pct']

            trade_profit = BUY_SIZE * trade_pnl_pct
            total_invested += BUY_SIZE
            total_profit += trade_profit
            symbol_profit += trade_profit
            symbol_trades += 1

            all_trades.append({
                'symbol': symbol,
                'entry_date': entry['date'],
                'entry_price': entry_price,
                'exit_date': exit_info['date'],
                'exit_type': exit_info['type'],
                'exit_price': exit_info['price'],
                'pnl_pct': trade_pnl_pct,
                'profit_$': trade_profit
            })

            print(f"  {entry['date'].strftime('%Y-%m-%d')}: "
                  f"Buy @ ${entry_price:.2f} → "
                  f"{exit_info['type']:12s} @ ${exit_info['price']:.2f} "
                  f"({trade_pnl_pct*100:+.2f}%) ${trade_profit:+.2f}")

        if symbol_trades > 0:
            print(f"  Subtotal: {symbol_trades} trades, ${symbol_profit:+.2f}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  BACKTEST SUMMARY")
    print(f"{'='*60}")
    print(f"  Total trades: {len(all_trades)}")
    print(f"  Total invested: ${total_invested:.2f}")
    print(f"  Total profit: ${total_profit:+.2f}")
    print(f"  ROI: {(total_profit / total_invested * 100):+.2f}%")

    if all_trades:
        df_trades = pd.DataFrame(all_trades)
        print(f"\n  Exit type distribution:")
        print(f"    {df_trades['exit_type'].value_counts().to_dict()}")
        print(f"\n  Average P&L per trade: {df_trades['pnl_pct'].mean()*100:+.2f}%")
        print(f"  Win rate: {(df_trades['pnl_pct'] > 0).sum() / len(df_trades) * 100:.1f}%")
        print(f"  Max gain: {df_trades['pnl_pct'].max()*100:+.2f}%")
        print(f"  Max loss: {df_trades['pnl_pct'].min()*100:+.2f}%")

if __name__ == "__main__":
    run_backtest()
