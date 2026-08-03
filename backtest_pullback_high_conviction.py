#!/usr/bin/env python3
"""Test pullback strategy with HIGH confidence only (>=70)"""
import yfinance as yf
import pandas as pd
from datetime import datetime

START_DATE = "2026-04-27"
END_DATE = "2026-07-27"
TOTAL_BUDGET = 2000
MAX_POSITION = 600
CONFIDENCE_THRESHOLD = 70  # HIGH conviction only

WATCHLIST = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'TSLA', 'AAPL', 'NFLX', 'SNPS', 'ADBE',
    'CRM', 'NOW', 'ACN', 'CDNS', 'INTU', 'BKNG', 'V', 'MA', 'AMAT', 'LRCX',
    'AMD', 'INTC', 'KEYS', 'ADI', 'MU', 'AVGO', 'AXP', 'BA', 'CAT', 'GE',
    'RTX', 'JNJ', 'PFE', 'KO', 'PEP', 'WMT', 'MCD', 'CMCSA', 'VZ', 'CVX',
    'XOM', 'COP', 'GILD', 'AMGN', 'LLY', 'AZO', 'COST', 'HD', 'PCAR', 'ENPH'
]

print(f"Loading data... ({START_DATE} to {END_DATE})")
data = yf.download(' '.join(WATCHLIST), start=START_DATE, end=END_DATE, progress=False)['Close']
dates = data.index.tolist()

trades = []
cash = TOTAL_BUDGET
positions = {}
watchlist = {}
spike_count = pullback_count = buy_count = 0

for day_idx, date in enumerate(dates[1:], start=1):
    prev_date = dates[day_idx - 1]
    today_prices = data.loc[date]
    prev_prices = data.loc[prev_date]
    pct_changes = ((today_prices - prev_prices) / prev_prices * 100).dropna()

    # Detect spikes 2%+
    new_spikes = pct_changes[pct_changes >= 2.0]
    for symbol, pct in new_spikes.items():
        if symbol not in watchlist and symbol not in positions:
            watchlist[symbol] = {
                'spike_date': prev_date,
                'spike_high': today_prices[symbol],
                'spike_pct': pct,
            }
            spike_count += 1

    # Check for pullbacks (high confidence: -1.5% to -2.5% pullback)
    buy_signals = []
    symbols_to_remove = []
    for symbol in list(watchlist.keys()):
        if symbol not in today_prices.index or symbol in positions:
            continue
        
        entry = watchlist[symbol]
        pullback_pct = (today_prices[symbol] - entry['spike_high']) / entry['spike_high'] * 100
        
        if -2.5 <= pullback_pct <= -1.5:  # Deep pullback = high confidence
            confidence = 75  # HIGH confidence
            buy_signals.append({
                'symbol': symbol,
                'confidence': confidence,
                'pullback_pct': pullback_pct,
                'entry_price': today_prices[symbol]
            })
            pullback_count += 1
            symbols_to_remove.append(symbol)
        elif (date - entry['spike_date']).days > 5 or pullback_pct < -3.0:
            symbols_to_remove.append(symbol)
    
    for symbol in symbols_to_remove:
        if symbol in watchlist:
            del watchlist[symbol]

    # Execute HIGH-confidence buys only
    for signal in buy_signals:
        symbol = signal['symbol']
        if signal['confidence'] < CONFIDENCE_THRESHOLD:
            continue
        
        entry_price = signal['entry_price']
        qty = min(MAX_POSITION // int(entry_price), int(cash / entry_price))
        if qty == 0 or cash < entry_price * qty:
            continue
        
        cost = entry_price * qty
        cash -= cost
        positions[symbol] = {
            'entry_price': entry_price,
            'qty': qty,
            'entry_date': date,
            'confidence': signal['confidence'],
            'pullback_pct': signal['pullback_pct']
        }
        if symbol in watchlist:
            del watchlist[symbol]
        buy_count += 1

    # Exit: +1.5% OR -2% stop OR 3 days
    for symbol in list(positions.keys()):
        if symbol not in today_prices.index:
            continue
        
        pos = positions[symbol]
        curr_price = today_prices[symbol]
        pnl_pct = (curr_price - pos['entry_price']) / pos['entry_price'] * 100
        days_held = (date - pos['entry_date']).days
        
        if pnl_pct >= 1.5 or pnl_pct <= -2.0 or days_held >= 3:
            pnl = (curr_price - pos['entry_price']) * pos['qty']
            cash += curr_price * pos['qty']
            trades.append({
                'symbol': symbol,
                'entry_price': pos['entry_price'],
                'exit_price': curr_price,
                'qty': pos['qty'],
                'pnl_pct': pnl_pct,
                'pnl': pnl
            })
            del positions[symbol]

# Close remaining
for symbol in list(positions.keys()):
    pos = positions[symbol]
    exit_price = data.loc[dates[-1], symbol]
    pnl = (exit_price - pos['entry_price']) * pos['qty']
    cash += exit_price * pos['qty']
    trades.append({
        'symbol': symbol,
        'entry_price': pos['entry_price'],
        'exit_price': exit_price,
        'qty': pos['qty'],
        'pnl_pct': (exit_price - pos['entry_price']) / pos['entry_price'] * 100,
        'pnl': pnl
    })

# Results
df = pd.DataFrame(trades)
if len(df) > 0:
    roi = (cash - TOTAL_BUDGET) / TOTAL_BUDGET * 100
    win_rate = len(df[df['pnl'] > 0]) / len(df) * 100 if len(df) > 0 else 0
    print(f"\nSpikes: {spike_count} | Pullbacks: {pullback_count} | Trades: {buy_count}")
    print(f"Trades Closed: {len(df)}")
    print(f"Win Rate: {win_rate:.1f}% | ROI: {roi:+.2f}%")
    print(f"Final Capital: ${cash:,.2f}")
    print(f"Total PnL: ${df['pnl'].sum():,.2f}")
else:
    print("No trades!")
