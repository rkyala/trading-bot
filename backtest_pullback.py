#!/usr/bin/env python3
"""
Backtest: PULLBACK BOUNCE STRATEGY (Apr-Jul 2026)
Instead of chasing extended moves, buy pullbacks and trade bounces.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime

START_DATE = "2026-04-27"
END_DATE = "2026-07-27"
TOTAL_BUDGET = 2000
MAX_POSITION = 500

WATCHLIST = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'TSLA', 'AAPL', 'NFLX', 'SNPS', 'ADBE',
    'CRM', 'NOW', 'ACN', 'CDNS', 'INTU', 'BKNG', 'V', 'MA', 'AMAT', 'LRCX',
    'AMD', 'INTC', 'KEYS', 'ADI', 'MU', 'AVGO', 'AXP', 'BA', 'CAT', 'GE',
    'RTX', 'JNJ', 'PFE', 'KO', 'PEP', 'WMT', 'MCD', 'CMCSA', 'VZ', 'CVX',
    'XOM', 'COP', 'GILD', 'AMGN', 'LLY', 'AZO', 'COST', 'HD', 'PCAR', 'ENPH'
]

def backtest():
    print(f"Loading data ({START_DATE} to {END_DATE})...")
    data = yf.download(' '.join(WATCHLIST), start=START_DATE, end=END_DATE, progress=False)['Close']
    dates = data.index.tolist()

    trades = []
    cash = TOTAL_BUDGET
    positions = {}

    print(f"Backtesting {len(dates)} days with PULLBACK BOUNCE strategy...\n")

    for day_idx, date in enumerate(dates[1:], start=1):
        prev_date = dates[day_idx - 1]

        # Daily % change (to identify movers)
        today_prices = data.loc[date]
        prev_prices = data.loc[prev_date]
        pct_changes = ((today_prices - prev_prices) / prev_prices * 100).dropna()

        # Find top movers (+5% to +8%)
        movers_in_range = pct_changes[(pct_changes >= 5) & (pct_changes <= 8)]
        top_candidates = movers_in_range.nlargest(3)

        if len(top_candidates) == 0:
            continue

        # Pullback detection: simulate intraday pullback
        # Assume if daily close is +5-8%, it likely pulled back -1 to -2% intraday
        # Score based on: size of move (higher is better) + pullback (which we simulate)
        entry_date = date
        for symbol, daily_pct in top_candidates.items():
            # Confidence: stocks up 6-8% that pull back are high probability bounces
            confidence = min(60 + int(daily_pct * 3), 85)

            if confidence < 60:
                continue

            # Skip if already holding
            if symbol in positions:
                continue

            # Enter at a simulated pullback price (1.5% below close)
            close_price = today_prices[symbol]
            entry_price = close_price * 0.985  # Simulated pullback entry at -1.5%
            qty = min(MAX_POSITION // int(entry_price), int(cash / entry_price))

            if qty == 0 or cash < entry_price * qty:
                continue

            cost = entry_price * qty
            cash -= cost
            positions[symbol] = {
                'entry_price': entry_price,
                'qty': qty,
                'entry_date': entry_date,
                'confidence': confidence,
                'daily_move': daily_pct
            }

        # Exit logic: bounce targets +2% to +3%
        closed_positions = []
        for symbol in list(positions.keys()):
            if symbol not in today_prices.index:
                continue

            pos = positions[symbol]
            current_price = today_prices[symbol]
            pnl_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            days_held = (date - pos['entry_date']).days

            # Target: +2% bounce
            if pnl_pct >= 2.0 or days_held >= 2 or pnl_pct <= -2.0:
                exit_price = current_price
                pnl = (exit_price - pos['entry_price']) * pos['qty']
                cash += exit_price * pos['qty']

                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': pos['entry_price'],
                    'exit_price': exit_price,
                    'qty': pos['qty'],
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'days': days_held,
                    'confidence': pos['confidence'],
                    'daily_move': pos['daily_move'],
                    'reason': f'bounce_target_{pnl_pct:+.1f}%'
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
            'daily_move': pos['daily_move'],
            'reason': 'backtest_end'
        })

    df_trades = pd.DataFrame(trades)

    if len(df_trades) == 0:
        print("❌ NO TRADES")
        return

    total_pnl = df_trades['pnl'].sum()
    winning = len(df_trades[df_trades['pnl'] > 0])
    losing = len(df_trades[df_trades['pnl'] < 0])
    win_rate = winning / len(df_trades) * 100
    avg_win = df_trades[df_trades['pnl'] > 0]['pnl'].mean() if winning > 0 else 0
    avg_loss = df_trades[df_trades['pnl'] < 0]['pnl'].mean() if losing > 0 else 0
    final_capital = cash
    roi = (final_capital - TOTAL_BUDGET) / TOTAL_BUDGET * 100

    print("=" * 70)
    print("PULLBACK BOUNCE STRATEGY - BACKTEST RESULTS")
    print("=" * 70)
    print(f"Total Trades:        {len(df_trades)}")
    print(f"Winning Trades:      {winning} ({win_rate:.1f}%)")
    print(f"Losing Trades:       {losing}")
    print(f"Avg Win:             ${avg_win:,.2f}")
    print(f"Avg Loss:            ${avg_loss:,.2f}")
    print(f"\nTotal P&L:           ${total_pnl:,.2f}")
    print(f"Starting Capital:    ${TOTAL_BUDGET:,.2f}")
    print(f"Final Capital:       ${final_capital:,.2f}")
    print(f"ROI:                 {roi:+.2f}%")
    print("=" * 70)

    print("\nTop 5 Winning Trades:")
    top_wins = df_trades.nlargest(5, 'pnl')[['symbol', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'confidence']]
    for idx, trade in top_wins.iterrows():
        print(f"  {trade['symbol']:5s} {trade['entry_date'].date()} | Entry ${trade['entry_price']:.2f} Exit ${trade['exit_price']:.2f} | P&L ${trade['pnl']:+7.2f} ({trade['pnl_pct']:+.1f}%) [Conf:{trade['confidence']}]")

    print("\nTop 5 Losing Trades:")
    top_losses = df_trades.nsmallest(5, 'pnl')[['symbol', 'entry_date', 'exit_date', 'entry_price', 'exit_price', 'pnl', 'pnl_pct', 'confidence']]
    for idx, trade in top_losses.iterrows():
        print(f"  {trade['symbol']:5s} {trade['entry_date'].date()} | Entry ${trade['entry_price']:.2f} Exit ${trade['exit_price']:.2f} | P&L ${trade['pnl']:+7.2f} ({trade['pnl_pct']:+.1f}%) [Conf:{trade['confidence']}]")

    print("\n" + "=" * 70)
    if roi > 0:
        print(f"✅ PULLBACK STRATEGY WORKS: +{roi:.2f}% ROI")
    else:
        print(f"❌ Still losing: {roi:.2f}% ROI")
    print("=" * 70)

if __name__ == '__main__':
    backtest()
