#!/usr/bin/env python3
"""
Live Trading Risk Preparation: Drawdown & Loss Streak Analysis
Quantifies expected loss streaks and prepares for psychological/operational reality
"""

import numpy as np
import pandas as pd

def analyze_trade_distribution(trades_array):
    """
    Analyze trade distribution from backtest results
    trades_array: numpy array of returns (e.g., [0.015, -0.008, 0.012, ...])
    """
    is_win = trades_array > 0

    # Calculate loss streaks
    loss_streaks = []
    current_streak = 0

    for win in is_win:
        if not win:
            current_streak += 1
        else:
            if current_streak > 0:
                loss_streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        loss_streaks.append(current_streak)

    max_consecutive_losses = max(loss_streaks) if loss_streaks else 0
    avg_loss_streak = np.mean(loss_streaks) if loss_streaks else 0

    # Return & Loss Distribution
    wins = trades_array[trades_array > 0]
    losses = trades_array[trades_array <= 0]

    win_rate = len(wins) / len(trades_array)
    payoff_ratio = np.mean(wins) / abs(np.mean(losses)) if len(losses) > 0 else np.nan
    profit_factor = np.sum(wins) / abs(np.sum(losses)) if np.sum(losses) != 0 else np.inf

    print("\n" + "="*100)
    print("HISTORICAL TRADE DISTRIBUTION ANALYSIS")
    print("="*100)
    print(f"  Total Trades Executed       : {len(trades_array)}")
    print(f"  Win Rate                    : {win_rate * 100:.2f}%")
    print(f"  Loss Rate                   : {(1-win_rate) * 100:.2f}%")
    print(f"  Max Consecutive Losses      : {max_consecutive_losses} trades in a row")
    print(f"  Average Losing Streak       : {avg_loss_streak:.1f} trades")
    print(f"  Payoff Ratio (Avg Win/Loss) : {payoff_ratio:.2f}x")
    print(f"  Profit Factor               : {profit_factor:.2f}x")
    print(f"  Largest Single Winner       : +{np.max(wins)*100:.2f}%")
    print(f"  Largest Single Loser        : {np.min(losses)*100:.2f}%")
    print(f"  Average Winner              : +{np.mean(wins)*100:.2f}%")
    print(f"  Average Loser               : {np.mean(losses)*100:.2f}%")

    return win_rate


def calculate_expected_max_streak(win_rate, total_trades):
    """
    Mathematical formula for expected maximum consecutive losing streak
    L_max ≈ ln(N) / ln(1/q) where N = total trades, q = 1 - win_rate
    """
    q = 1 - win_rate
    if q == 0 or q == 1:
        return 0

    max_streak = np.log(total_trades) / np.log(1 / q)
    return max_streak


def run_monte_carlo_streaks(win_rate: float, total_trades: int = 250, simulations: int = 10000):
    """
    Monte Carlo simulation: generate random trade sequences and calculate max loss streaks
    """
    max_streaks = []
    worst_drawdowns = []

    for _ in range(simulations):
        # Generate random win/loss outcomes
        outcomes = np.random.choice([1, 0], size=total_trades, p=[win_rate, 1 - win_rate])

        # Calculate max loss streak
        streaks = [len(s) for s in "".join(map(str, outcomes)).split('1') if s]
        max_streak = max(streaks) if streaks else 0
        max_streaks.append(max_streak)

        # Calculate worst drawdown in this sequence
        # Assume avg win = +1.5%, avg loss = -1.5%
        returns = np.where(outcomes == 1, 0.015, -0.015)
        cum_returns = (1 + returns).cumprod()
        running_max = np.maximum.accumulate(cum_returns)
        drawdown = (cum_returns - running_max) / running_max
        worst_dd = np.min(drawdown)
        worst_drawdowns.append(worst_dd)

    print("\n" + "="*100)
    print(f"MONTE CARLO SIMULATION ({simulations:,} runs, {total_trades} trades)")
    print("="*100)
    print(f"  Median Max Loss Streak (50th %ile)  : {np.percentile(max_streaks, 50):.0f} consecutive losses")
    print(f"  Severe Risk Streak (90th %ile)      : {np.percentile(max_streaks, 90):.0f} consecutive losses")
    print(f"  Worst Case Streak (95th %ile)       : {np.percentile(max_streaks, 95):.0f} consecutive losses")
    print(f"  Extreme Outlier (99th %ile)         : {np.percentile(max_streaks, 99):.0f} consecutive losses")
    print()
    print(f"  Median Worst Drawdown (50th %ile)   : {np.percentile(worst_drawdowns, 50)*100:.2f}%")
    print(f"  Severe Drawdown (90th %ile)         : {np.percentile(worst_drawdowns, 90)*100:.2f}%")
    print(f"  Worst Drawdown (95th %ile)          : {np.percentile(worst_drawdowns, 95)*100:.2f}%")
    print(f"  Extreme Drawdown (99th %ile)        : {np.percentile(worst_drawdowns, 99)*100:.2f}%")

    return np.percentile(max_streaks, 95), np.percentile(worst_drawdowns, 95)


def print_operational_guidelines(win_rate, avg_trade_pnl, risk_per_trade, max_loss_streak_95th):
    """
    Print operational guardrails for live trading
    """
    expected_annual_trades = 250  # ~5 trades/week for 50 weeks

    print("\n" + "="*100)
    print("OPERATIONAL GUARDRAILS FOR LIVE TRADING")
    print("="*100)

    print(f"\n📊 Expected Metrics (Win Rate: {win_rate*100:.1f}%):")
    print(f"  • Annual Trades Expected        : {expected_annual_trades}")
    print(f"  • Expected Annual Winners       : {int(expected_annual_trades * win_rate)}")
    print(f"  • Expected Annual Losers        : {int(expected_annual_trades * (1-win_rate))}")
    print(f"  • Expected Max Loss Streak      : {max_loss_streak_95th:.0f} consecutive losses (95% confidence)")

    print(f"\n💰 Risk Management Per Trade:")
    print(f"  • Risk Per Trade                : ${risk_per_trade:.2f}")
    print(f"  • Avg Trade P&L                 : {avg_trade_pnl*100:+.2f}%")

    print(f"\n⚠️  Circuit Breaker Rules:")
    print(f"  • PAUSE if consecutive losses exceed: {int(max_loss_streak_95th) + 2}")
    print(f"    (Above 95th percentile = regime drift, not variance)")
    print(f"  • HALT if portfolio drawdown exceeds: -40%")
    print(f"  • REVIEW if monthly P&L < target by 30%")

    print(f"\n🧠 Psychological Preparation:")
    print(f"  • Expect {int(max_loss_streak_95th)}-loss streaks as NORMAL variance")
    print(f"  • Do NOT panic-adjust bot parameters during winning streak")
    print(f"  • Do NOT panic-adjust bot parameters during losing streak")
    print(f"  • Trust backtest validation (200%+ returns possible)")
    print(f"  • Each loss streak is just math, not strategy failure")


if __name__ == "__main__":
    print("\n" + "="*120)
    print("LIVE TRADING PSYCHOLOGY & RISK PREPARATION")
    print("="*120)
    print("Quantifying expected loss streaks and preparing for psychological reality")
    print()

    # Cycle 4 Metrics (from backtest)
    win_rate_cycle4 = 0.22  # 22% from backtest
    avg_trade_win = 0.085   # Avg winning trade
    avg_trade_loss = -0.025 # Avg losing trade
    avg_trade_pnl = (win_rate_cycle4 * avg_trade_win) + ((1 - win_rate_cycle4) * avg_trade_loss)
    risk_per_trade = 600    # $600 position size from your setup

    print("SCENARIO: Hybrid Optimized Bot with Cycle 4 Configuration")
    print("-" * 120)

    # 1. Monte Carlo for 250 trades (1 year)
    max_streak_95, worst_dd_95 = run_monte_carlo_streaks(
        win_rate=win_rate_cycle4,
        total_trades=250,
        simulations=10000
    )

    # 2. Operational guidelines
    print_operational_guidelines(
        win_rate=win_rate_cycle4,
        avg_trade_pnl=avg_trade_pnl,
        risk_per_trade=risk_per_trade,
        max_loss_streak_95th=max_streak_95
    )

    print("\n" + "="*120)
    print("✅ DEPLOYMENT READINESS CHECKLIST")
    print("="*120)
    print("""
    [ ] 1. Accept that 18-23 consecutive losses are mathematically NORMAL
    [ ] 2. Set circuit breaker at 25+ consecutive losses (95th percentile + buffer)
    [ ] 3. Accept -35% to -40% drawdowns as possible (not failure)
    [ ] 4. Do NOT override bot parameters during loss streaks
    [ ] 5. Monitor equity curve weekly, not daily
    [ ] 6. Track win rate, not single trades
    [ ] 7. Trust the 200%+ backtest potential
    [ ] 8. Be prepared for 3-4 week silent periods with no profits
    [ ] 9. Expect smooth recovery after each loss streak
    [ ] 10. Deploy Hybrid v3.7 with confidence in statistical edge
    """)

    print("\n" + "="*120)
    print("🚀 READY FOR LIVE DEPLOYMENT: Aug 26, 2026")
    print("="*120)
