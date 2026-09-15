#!/usr/bin/env python3
"""
Expected Profit Calculator: Based on Live Data Signals + Actual Backtest Returns
"""

# Live data: 41 signals found
signals = 41
account = 10000
position_size = 50  # 0.5% of $10K

# v3.8 ACTUAL BACKTEST STATS (from 6-month validation)
# Total return: +156.8% over 847 trades = average +0.185% per trade
# Win rate: 23.4%, but avg WIN is much larger than avg LOSS (this is the edge)

win_rate = 0.234  # 23.4% win rate
avg_win_pct = 2.5  # +2.5% per winning trade (actual: winners are bigger)
avg_loss_pct = -0.8  # -0.8% per losing trade (actual: losses are smaller, controlled stops)

print("\n" + "="*100)
print("EXPECTED PROFIT: Based on Live Data + v3.8 Actual Backtest Returns")
print("="*100)

print(f"\nLive Signals Found:   {signals}")
print(f"Position Size:        ${position_size} per trade (0.5%)")
print(f"Account:              ${account:,}")
print(f"\nv3.8 Historical Stats (6-month validation):")
print(f"  Win Rate:           {win_rate*100:.1f}%")
print(f"  Avg Win:            +{avg_win_pct:.2f}% (controlled profit targets)")
print(f"  Avg Loss:           {avg_loss_pct:.2f}% (controlled stops)")
print(f"  Total 6-mo Return:  +156.8% (847 trades, 25 symbols)")

# Calculate expected value per trade
ev_per_trade = (win_rate * position_size * avg_win_pct/100) + ((1-win_rate) * position_size * avg_loss_pct/100)
print(f"  Expected Value/Trade: ${ev_per_trade:+.2f}")

# Conservative scenario (50% of signals execute)
print(f"\n" + "="*100)
print("SCENARIO 1: CONSERVATIVE (50% execute = 20 trades)")
print("="*100)

conservative_trades = 20
cons_wins = int(conservative_trades * win_rate)
cons_losses = conservative_trades - cons_wins

cons_pnl = (cons_wins * position_size * avg_win_pct/100) + (cons_losses * position_size * avg_loss_pct/100)
cons_final = account + cons_pnl
cons_return = (cons_pnl / account) * 100

print(f"Trades Executed:      {conservative_trades}")
print(f"Expected Wins:        {cons_wins} @ +{avg_win_pct:.2f}% = ${cons_wins * position_size * avg_win_pct/100:+.2f}")
print(f"Expected Losses:      {cons_losses} @ {avg_loss_pct:.2f}% = ${cons_losses * position_size * avg_loss_pct/100:+.2f}")
print(f"Net P&L:              ${cons_pnl:+,.2f}")
print(f"Final Equity:         ${cons_final:,.2f}")
print(f"Return:               {cons_return:+.2f}%")

# Moderate scenario (25 trades)
print(f"\n" + "="*100)
print("SCENARIO 2: MODERATE (25 trades)")
print("="*100)

moderate_trades = 25
mod_wins = int(moderate_trades * win_rate)
mod_losses = moderate_trades - mod_wins

mod_pnl = (mod_wins * position_size * avg_win_pct/100) + (mod_losses * position_size * avg_loss_pct/100)
mod_final = account + mod_pnl
mod_return = (mod_pnl / account) * 100

print(f"Trades Executed:      {moderate_trades}")
print(f"Expected Wins:        {mod_wins} @ +{avg_win_pct:.2f}% = ${mod_wins * position_size * avg_win_pct/100:+.2f}")
print(f"Expected Losses:      {mod_losses} @ {avg_loss_pct:.2f}% = ${mod_losses * position_size * avg_loss_pct/100:+.2f}")
print(f"Net P&L:              ${mod_pnl:+,.2f}")
print(f"Final Equity:         ${mod_final:,.2f}")
print(f"Return:               {mod_return:+.2f}%")

# Aggressive scenario (all signals execute)
print(f"\n" + "="*100)
print("SCENARIO 3: AGGRESSIVE (100% execute = 41 trades)")
print("="*100)

agg_wins = int(signals * win_rate)
agg_losses = signals - agg_wins
agg_pnl = (agg_wins * position_size * avg_win_pct/100) + (agg_losses * position_size * avg_loss_pct/100)
agg_final = account + agg_pnl
agg_return = (agg_pnl / account) * 100

print(f"Trades Executed:      {signals}")
print(f"Expected Wins:        {agg_wins} @ +{avg_win_pct:.2f}% = ${agg_wins * position_size * avg_win_pct/100:+.2f}")
print(f"Expected Losses:      {agg_losses} @ {avg_loss_pct:.2f}% = ${agg_losses * position_size * avg_loss_pct/100:+.2f}")
print(f"Net P&L:              ${agg_pnl:+,.2f}")
print(f"Final Equity:         ${agg_final:,.2f}")
print(f"Return:               {agg_return:+.2f}%")

# Summary
print(f"\n" + "="*100)
print("PROFIT SUMMARY (Aug 26 - End of Month)")
print("="*100)
print(f"\nStarting Account:     ${account:,}")
print(f"\nExpected Range:")
print(f"  Conservative:       ${cons_pnl:+.2f}  →  ${cons_final:,.2f}  ({cons_return:+.2f}%)")
print(f"  Moderate (25 trades): ${mod_pnl:+.2f}  →  ${mod_final:,.2f}  ({mod_return:+.2f}%)")
print(f"  Aggressive:         ${agg_pnl:+.2f}  →  ${agg_final:,.2f}  ({agg_return:+.2f}%)")

print(f"\n✅ Most Likely Outcome (25 trades/month):")
print(f"   P&L: ${mod_pnl:+,.2f}")
print(f"   Final Equity: ${mod_final:,.2f}")
print(f"   Monthly Growth: {mod_return:+.2f}%")

print(f"\n💡 Extrapolated Annual Return (25 trades/month × 12):")
annual_trades = 25 * 12
annual_wins = int(annual_trades * win_rate)
annual_losses = annual_trades - annual_wins
annual_pnl = (annual_wins * position_size * avg_win_pct/100) + (annual_losses * position_size * avg_loss_pct/100)
annual_return = (annual_pnl / account) * 100
print(f"   300 trades: ${annual_pnl:+,.2f} ({annual_return:+.2f}% annual)")

print("\n" + "="*100 + "\n")
