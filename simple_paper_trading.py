#!/usr/bin/env python3
"""
Simple Paper Trading Simulator
Zero cost, uses your existing mean-reversion strategy
Generates daily performance reports
"""

import json
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

print("\n" + "="*70)
print("  SIMPLE PAPER TRADING (Zero Cost)")
print("="*70 + "\n")

# Configuration
SYMBOLS = ["INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS", "AMAT"]
INITIAL = 10000
MAX_POS = 1500
DAYS_BACK = 180  # 6 months historical

# Create report directory
os.makedirs("paper_reports", exist_ok=True)

# Fetch data
print(f"Fetching {len(SYMBOLS)} stocks, {DAYS_BACK} days...")
end_date = datetime.now()
start_date = end_date - timedelta(days=DAYS_BACK)

data = {}
for s in SYMBOLS:
    df = yf.download(s, start=start_date, end=end_date, progress=False)
    if not df.empty:
        data[s] = df
        print(f"  ✓ {s}: {len(df)} days")

# Simulate trading
cash = INITIAL
positions = {}
trades = []
daily_values = []

print(f"\nSimulating {len(data[SYMBOLS[0]])} days of trading...\n")

for day_idx in range(1, len(data[SYMBOLS[0]])):
    day_date = data[SYMBOLS[0]].index[day_idx]

    # Check each stock for mean-reversion opportunity
    for symbol in SYMBOLS:
        if symbol not in data or len(data[symbol]) <= day_idx:
            continue

        prices = data[symbol]['Close'].values.astype(float)

        # Mean-reversion signal: stock down 2% today, buy
        if day_idx > 0:
            price_prev = float(prices[day_idx - 1])
            price_curr = float(prices[day_idx])
            change_pct = (price_curr - price_prev) / price_prev

            # BUY on -2% pullback
            if change_pct < -0.02 and cash > MAX_POS * 0.1 and symbol not in positions:
                qty = float(min(MAX_POS / price_curr, cash / price_curr * 0.9))
                if qty > 0:
                    cost = float(qty * price_curr)
                    cash = float(cash - cost)
                    positions[symbol] = {'qty': qty, 'entry': float(price_curr), 'date': day_date}
                    trades.append({
                        'date': day_date,
                        'symbol': symbol,
                        'action': 'BUY',
                        'price': price_curr,
                        'qty': qty,
                        'cost': cost
                    })

            # SELL when up 1% (take profit)
            elif symbol in positions and change_pct > 0.01:
                qty = float(positions[symbol]['qty'])
                entry = float(positions[symbol]['entry'])
                proceeds = float(qty * price_curr)
                pnl = float(proceeds - (qty * entry))
                pnl_pct = float((price_curr - entry) / entry)

                cash = float(cash + proceeds)
                del positions[symbol]
                trades.append({
                    'date': day_date,
                    'symbol': symbol,
                    'action': 'SELL',
                    'price': price_curr,
                    'qty': qty,
                    'proceeds': proceeds,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct
                })

    # Calculate portfolio value
    portfolio_val = float(cash)
    for symbol, pos in positions.items():
        if symbol in data and len(data[symbol]) > day_idx:
            price = float(data[symbol]['Close'].iloc[day_idx])
            portfolio_val += float(pos['qty'] * price)

    daily_values.append(float(portfolio_val))

# Calculate metrics
daily_values = np.array(daily_values)
total_return = (daily_values[-1] - INITIAL) / INITIAL
annual_return = total_return * (252 / len(daily_values))

if len(daily_values) > 1:
    returns = np.diff(daily_values) / daily_values[:-1]
    sharpe = np.mean(returns) / (np.std(returns) + 1e-8) * np.sqrt(252)
    max_dd = np.min((daily_values - np.maximum.accumulate(daily_values)) / np.maximum.accumulate(daily_values))
else:
    sharpe = 0
    max_dd = 0

sell_trades = [t for t in trades if t['action'] == 'SELL']
win_trades = len([t for t in sell_trades if t.get('pnl', 0) > 0])
win_rate = (win_trades / len(sell_trades) * 100) if sell_trades else 0

# Print results
print("="*70)
print("  PAPER TRADING RESULTS")
print("="*70)
print(f"\nInitial:         ${INITIAL:,.0f}")
print(f"Final Value:     ${daily_values[-1]:,.0f}")
print(f"Total P&L:       ${daily_values[-1] - INITIAL:+,.0f}")
print(f"Return:          {total_return*100:+.2f}%")
print(f"Annualized:      {annual_return*100:+.2f}%\n")

print(f"Sharpe Ratio:    {sharpe:.2f}")
print(f"Max Drawdown:    {max_dd*100:.2f}%\n")

print(f"Total Trades:    {len(trades)}")
print(f"Buy Trades:      {len([t for t in trades if t['action']=='BUY'])}")
print(f"Sell Trades:     {len(sell_trades)}")
print(f"Win Rate:        {win_rate:.1f}%\n")

print("="*70)
print(f"✅ Paper trading complete!")
print(f"\nNext step: Deploy real bot when confident in results")
print(f"Cost to go live: $840/year (Claude monitoring)")
print("="*70 + "\n")

# Save results
results = {
    'initial': INITIAL,
    'final_value': float(daily_values[-1]),
    'total_return_pct': float(total_return * 100),
    'annual_return_pct': float(annual_return * 100),
    'sharpe_ratio': float(sharpe),
    'max_drawdown_pct': float(max_dd * 100),
    'total_trades': len(trades),
    'win_rate_pct': float(win_rate),
    'dates': {
        'start': str(start_date.date()),
        'end': str(end_date.date())
    }
}

with open("paper_results.json", "w") as f:
    json.dump(results, f, indent=2)

df_trades = pd.DataFrame(trades)
df_trades.to_csv("paper_trades.csv", index=False)

print(f"Results saved to:")
print(f"  - paper_results.json (metrics)")
print(f"  - paper_trades.csv (all trades)\n")
