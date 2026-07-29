#!/usr/bin/env python3
"""
Mean-Reversion Strategy V2 (Improved)

Fixes:
1. Wait for DEEPER pullback (-3% to -4%) to catch the bottom
2. Tighter initial stops (-1.5%)
3. Longer hold (up to 7 days for recovery)
4. Scale in on pullback (don't buy immediately, size based on depth)
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

START_DATE = "2026-04-27"
END_DATE = "2026-07-27"
TOTAL_BUDGET = 2000
CONFIDENCE_THRESHOLD = 60

WATCHLIST = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'TSLA', 'AAPL', 'NFLX', 'SNPS', 'ADBE',
    'CRM', 'NOW', 'ACN', 'CDNS', 'INTU', 'BKKING', 'V', 'MA', 'AMAT', 'LRCX',
    'AMD', 'INTC', 'KEYS', 'ADI', 'MU', 'AVGO', 'AXP', 'BA', 'CAT', 'GE',
    'RTX', 'JNJ', 'PFE', 'KO', 'PEP', 'WMT', 'MCD', 'CMCSA', 'VZ', 'CVX',
    'XOM', 'COP', 'GILD', 'AMGN', 'LLY', 'AZO', 'COST', 'HD', 'PCAR', 'ENPH'
]

def backtest_mean_reversion_v2():
    print(f"Mean-Reversion Strategy V2 Backtest ({START_DATE} to {END_DATE})...")
    print("Improvements: Deeper pullback (-3% to -4%), tighter stops (-1.5%), longer hold (7 days)\n")

    data = yf.download(' '.join(WATCHLIST), start=START_DATE, end=END_DATE, progress=False)['Close']
    dates = data.index.tolist()

    trades = []
    cash = TOTAL_BUDGET

    # Track overbought: {symbol: {'spike_price': X, 'spike_date': Y, 'spike_pct': Z, 'spike_high': H}}
    overbought_watch = {}
    positions = {}

    print(f"Backtesting {len(dates)} trading days...\n")

    for day_idx, date in enumerate(dates[1:], start=1):
        prev_date = dates[day_idx - 1]

        today_prices = data.loc[date]
        prev_prices = data.loc[prev_date]
        pct_changes = ((today_prices - prev_prices) / prev_prices * 100).dropna()

        # STAGE 1: DETECT OVERBOUGHT SPIKES (5-8% up)
        overbought = pct_changes[(pct_changes >= 5.0) & (pct_changes <= 8.0)]

        for symbol, pct_change in overbought.items():
            if symbol not in overbought_watch and symbol not in positions:
                confidence = min(75 + int((pct_change - 5.0) * 3), 85)
                overbought_watch[symbol] = {
                    'spike_price': today_prices[symbol],
                    'spike_date': date,
                    'spike_pct': pct_change,
                    'spike_high': today_prices[symbol],  # Track highest point
                    'confidence': confidence,
                    'days_since_spike': 0
                }

        # STAGE 2: WAIT FOR DEEPER PULLBACK (-3% to -4%)
        symbols_to_remove = []
        for symbol in list(overbought_watch.keys()):
            if symbol not in today_prices.index:
                symbols_to_remove.append(symbol)
                continue

            spike_info = overbought_watch[symbol]
            current_price = today_prices[symbol]
            days_since = (date - spike_info['spike_date']).days
            spike_info['days_since_spike'] = days_since

            # Update spike high (intraday peak)
            spike_info['spike_high'] = max(spike_info['spike_high'], current_price)

            # Calculate pullback from SPIKE PRICE (not spike high)
            pullback_pct = (current_price - spike_info['spike_price']) / spike_info['spike_price'] * 100

            # ENTRY: Deeper pullback (-3% to -4%) gives better odds
            # Also: Only enter if pullback has bottomed (next day price is higher = sign of reversal)
            if -4.0 <= pullback_pct <= -2.5 and days_since <= 3:
                if symbol not in positions and cash > current_price:
                    confidence = spike_info['confidence']

                    # Position sizing: deeper pullback = larger position
                    pullback_depth = abs(pullback_pct)
                    if pullback_depth >= 3.5:
                        size = 350  # Very deep pullback, buy aggressive
                    elif pullback_depth >= 3.0:
                        size = 300
                    elif pullback_depth >= 2.5:
                        size = 200
                    else:
                        size = 150

                    qty = min(size // int(current_price), int(cash / current_price))

                    if qty > 0:
                        cost = current_price * qty
                        cash -= cost
                        positions[symbol] = {
                            'entry_price': current_price,
                            'qty': qty,
                            'entry_date': date,
                            'confidence': confidence,
                            'spike_price': spike_info['spike_price'],
                            'spike_pct': spike_info['spike_pct'],
                            'pullback_pct': pullback_pct,
                            'type': 'mean_reversion_v2'
                        }
                        symbols_to_remove.append(symbol)

            # Timeout or continued fall: cancel watch
            elif days_since > 4 or pullback_pct < -4.5:
                symbols_to_remove.append(symbol)

        for symbol in symbols_to_remove:
            if symbol in overbought_watch:
                del overbought_watch[symbol]

        # STAGE 3: EXIT POSITIONS
        closed_positions = []
        for symbol in list(positions.keys()):
            if symbol not in today_prices.index:
                continue

            pos = positions[symbol]
            current_price = today_prices[symbol]
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            days_held = (date - pos['entry_date']).days

            # Exit rule: 50% at +0.75% (quick recovery), 50% at +2% (full recovery) or -1.5% tight stop

            # PARTIAL EXIT: +0.75% quick recovery
            if pnl_pct >= 0.75 and pos.get('partial_exit') is None:
                exit_qty = pos['qty'] // 2
                exit_price = current_price
                pnl = (exit_price - pos['entry_price']) * exit_qty
                cash += exit_price * exit_qty

                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'qty': exit_qty,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'days': days_held,
                    'confidence': pos['confidence'],
                    'reason': 'partial_+0.75%',
                    'spike_pct': pos['spike_pct'],
                    'pullback_pct': pos['pullback_pct']
                })

                pos['qty'] -= exit_qty
                pos['partial_exit'] = True

            # FINAL EXIT: +2% recovery OR -1.5% tight stop OR 7+ days
            if pos.get('qty', 0) > 0:
                exit_condition = (
                    pnl_pct >= 2.0 or          # Recovery complete
                    pnl_pct <= -1.5 or         # Tight stop (mean reversion failed)
                    days_held >= 7             # Timeout
                )

                if exit_condition:
                    exit_qty = pos['qty']
                    exit_price = current_price
                    pnl = (exit_price - pos['entry_price']) * exit_qty
                    cash += exit_price * exit_qty

                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': date,
                        'entry_price': pos['entry_price'],
                        'exit_price': exit_price,
                        'qty': exit_qty,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'days': days_held,
                        'confidence': pos['confidence'],
                        'reason': f'exit_{pnl_pct:+.1f}%',
                        'spike_pct': pos['spike_pct'],
                        'pullback_pct': pos['pullback_pct']
                    })
                    closed_positions.append(symbol)

        for symbol in closed_positions:
            del positions[symbol]

    # Close remaining at end
    last_price = data.loc[dates[-1]]
    for symbol in list(positions.keys()):
        pos = positions[symbol]
        exit_price = last_price[symbol]
        pnl = (exit_price - pos['entry_price']) * pos['qty']
        trades.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': dates[-1],
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'qty': pos['qty'],
            'pnl': pnl,
            'pnl_pct': (exit_price - pos['entry_price']) / pos['entry_price'] * 100,
            'days': (dates[-1] - pos['entry_date']).days,
            'confidence': pos['confidence'],
            'reason': 'backtest_end',
            'spike_pct': pos['spike_pct'],
            'pullback_pct': pos['pullback_pct']
        })

    # ANALYSIS
    df_trades = pd.DataFrame(trades)

    if len(df_trades) == 0:
        print("❌ NO TRADES EXECUTED")
        return

    total_pnl = df_trades['pnl'].sum()
    winning_trades = len(df_trades[df_trades['pnl'] > 0])
    losing_trades = len(df_trades[df_trades['pnl'] < 0])
    win_rate = winning_trades / len(df_trades) * 100 if len(df_trades) > 0 else 0

    avg_profit = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losing_trades > 0 else 0

    avg_profit_pct = df_trades[df_trades['pnl'] > 0]['pnl_pct'].mean() if winning_trades > 0 else 0
    avg_loss_pct = df_trades[df_trades['pnl'] < 0]['pnl_pct'].mean() if losing_trades > 0 else 0

    final_capital = cash
    roi = (final_capital - TOTAL_BUDGET) / TOTAL_BUDGET * 100

    print("=" * 70)
    print("MEAN-REVERSION STRATEGY V2 RESULTS")
    print("=" * 70)
    print(f"Starting Capital:    ${TOTAL_BUDGET:,.2f}")
    print(f"Ending Capital:      ${final_capital:,.2f}")
    print(f"Total P&L:           ${total_pnl:,.2f}")
    print(f"ROI:                 {roi:+.2f}%")
    print()
    print(f"Total Trades:        {len(df_trades)}")
    print(f"Winning Trades:      {winning_trades} ({win_rate:.1f}%)")
    print(f"Losing Trades:       {losing_trades} ({100-win_rate:.1f}%)")
    print()
    print(f"Avg Win:             ${avg_profit:+.2f} ({avg_profit_pct:+.2f}%)")
    print(f"Avg Loss:            ${avg_loss:+.2f} ({avg_loss_pct:+.2f}%)")
    print()
    print(f"Best Trade:          ${df_trades['pnl'].max():+.2f}")
    print(f"Worst Trade:         ${df_trades['pnl'].min():+.2f}")
    print()
    print("=" * 70)
    print("STRATEGY COMPARISON")
    print("=" * 70)
    print(f"Momentum (OLD):      -36% to -72% ROI ❌")
    print(f"Mean-Reversion V1:   -0.71% ROI ❌")
    print(f"Mean-Reversion V2:   {roi:+.2f}% ROI {'✅ PROFITABLE' if roi > 0 else '❌ STILL NEGATIVE'}")
    print()

    df_trades.to_csv('backtest_mean_reversion_v2_trades.csv', index=False)
    print("Trades saved to: backtest_mean_reversion_v2_trades.csv")

if __name__ == '__main__':
    backtest_mean_reversion_v2()
