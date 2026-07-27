#!/usr/bin/env python3
"""
Daily learning module: Analyze trades, propose strategy variants, backtest, auto-deploy.
"""
import json
import logging
from datetime import datetime, timedelta
import subprocess
import yfinance as yf
import pandas as pd
import anthropic

log = logging.getLogger(__name__)

BACKTEST_START = "2026-04-27"
BACKTEST_END = "2026-07-27"
WATCHLIST = [
    'NVDA', 'MSFT', 'META', 'GOOGL', 'AMZN', 'TSLA', 'AAPL', 'NFLX', 'SNPS', 'ADBE',
    'CRM', 'NOW', 'ACN', 'CDNS', 'INTU', 'BKKING', 'V', 'MA', 'AMAT', 'LRCX',
    'AMD', 'INTC', 'KEYS', 'ADI', 'MU', 'AVGO', 'AXP', 'BA', 'CAT', 'GE',
    'RTX', 'JNJ', 'PFE', 'KO', 'PEP', 'WMT', 'MCD', 'CMCSA', 'VZ', 'CVX',
    'XOM', 'COP', 'GILD', 'AMGN', 'LLY', 'AZO', 'COST', 'HD', 'PCAR', 'ENPH'
]

def analyze_daily_trades(trades, current_threshold=55):
    """Analyze today's trades and identify improvement opportunities."""
    if not trades:
        return None

    trades_df = pd.DataFrame(trades)

    # Win/loss by confidence bracket
    brackets = {}
    for bracket_start in [55, 60, 65, 70, 75, 80]:
        bracket_end = bracket_start + 5
        bracket_trades = trades_df[
            (trades_df['confidence'] >= bracket_start) &
            (trades_df['confidence'] < bracket_end)
        ]
        if len(bracket_trades) > 0:
            wins = len(bracket_trades[bracket_trades['pnl'] > 0])
            total = len(bracket_trades)
            win_rate = wins / total * 100
            avg_win = bracket_trades[bracket_trades['pnl'] > 0]['pnl'].mean() if wins > 0 else 0
            avg_loss = bracket_trades[bracket_trades['pnl'] < 0]['pnl'].mean() if len(bracket_trades) - wins > 0 else 0

            brackets[f"{bracket_start}-{bracket_end}"] = {
                "count": total,
                "wins": wins,
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss
            }

    return {
        "total_trades": len(trades_df),
        "daily_pnl": trades_df['pnl'].sum(),
        "confidence_brackets": brackets
    }

def propose_strategy_variant(client, analysis, current_config):
    """Claude proposes strategy variant based on trade analysis."""

    prompt = f"""Analyze today's trading and propose ONE strategy variant to backtest:

Current Config:
  - Confidence threshold: {current_config['threshold']}
  - Cover at: {current_config['cover1']}% and {current_config['cover2']}%
  - Current ROI (backtest): {current_config['current_roi']}%

Today's Trades:
  - Total: {analysis['total_trades']}
  - Daily P&L: ${analysis['daily_pnl']:.2f}

Win Rate by Confidence:
"""
    for bracket, stats in analysis['confidence_brackets'].items():
        prompt += f"\n  - {bracket}: {stats['win_rate']:.1f}% ({stats['wins']}/{stats['count']}), avg win ${stats['avg_win']:.2f}, avg loss ${stats['avg_loss']:.2f}"

    prompt += f"""

Based on this analysis, propose ONE change to improve the strategy. Options:
1. Raise/lower confidence threshold (e.g., 55→65 or 65→55)
2. Adjust cover prices (e.g., -2%/-5% to -1.5%/-4.5%)
3. Change position sizing based on confidence

Response format (JSON only):
{{"variant": "raise_threshold_to_65", "rationale": "Confidence 60-65 has low win rate, 65-70 is strong", "config": {{"threshold": 65, "cover1": -2, "cover2": -5}}}}"""

    resp = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    try:
        text = resp.content[0].text
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            return json.loads(text[json_start:json_end])
    except:
        pass

    return None

def run_backtest_variant(variant_config):
    """Run backtest with variant config and return ROI."""

    log.info(f"Backtesting variant: {variant_config['variant']}")

    # Minimal parameterized backtest
    data = yf.download(' '.join(WATCHLIST), start=BACKTEST_START, end=BACKTEST_END, progress=False)['Close']
    dates = data.index.tolist()

    trades = []
    cash = 2000
    positions = {}

    threshold = variant_config['config']['threshold']
    cover1_pct = variant_config['config']['cover1'] / 100.0
    cover2_pct = variant_config['config']['cover2'] / 100.0

    for day_idx, date in enumerate(dates[1:], start=1):
        prev_date = dates[day_idx - 1]
        today_prices = data.loc[date]
        prev_prices = data.loc[prev_date]
        pct_changes = ((today_prices - prev_prices) / prev_prices * 100).dropna()

        movers = pct_changes[(pct_changes >= 5) & (pct_changes <= 8)]
        top_candidates = movers.nlargest(3)

        for symbol, daily_pct in top_candidates.items():
            confidence = min(65 + int(daily_pct * 2), 85)

            if confidence < threshold or symbol in positions:
                continue

            short_price = today_prices[symbol]
            qty = min(500 // int(short_price), int(cash / short_price))

            if qty == 0 or cash < short_price * qty:
                continue

            cash += short_price * qty
            positions[symbol] = {
                'short_price': short_price,
                'qty_total': qty,
                'qty_riding': qty,
                'entry_date': date,
                'confidence': confidence,
                'partial_covered': False
            }

        closed_positions = []
        for symbol in list(positions.keys()):
            if symbol not in today_prices.index:
                continue

            pos = positions[symbol]
            current_price = today_prices[symbol]
            pnl_pct = (pos['short_price'] - current_price) / pos['short_price'] * 100
            days_held = (date - pos['entry_date']).days

            if not pos['partial_covered'] and pnl_pct >= abs(cover1_pct * 100):
                cover_qty = pos['qty_total'] // 2
                pnl = (pos['short_price'] - current_price) * cover_qty
                cash -= current_price * cover_qty
                trades.append({'pnl': pnl})
                pos['qty_riding'] = pos['qty_total'] - cover_qty
                pos['partial_covered'] = True

            if pos['qty_riding'] > 0:
                exit_cond = (pnl_pct >= abs(cover2_pct * 100)) or (pnl_pct <= -3.0) or (days_held >= 5)
                if exit_cond:
                    cover_qty = pos['qty_riding']
                    pnl = (pos['short_price'] - current_price) * cover_qty
                    cash -= current_price * cover_qty
                    trades.append({'pnl': pnl})
                    closed_positions.append(symbol)

        for symbol in closed_positions:
            del positions[symbol]

    df_trades = pd.DataFrame(trades) if trades else pd.DataFrame({'pnl': []})
    total_pnl = df_trades['pnl'].sum() if len(df_trades) > 0 else 0
    final_capital = cash
    roi = (final_capital - 2000) / 2000 * 100

    return roi

def daily_learning(client, state):
    """Run daily learning: analyze, propose variant, backtest, deploy if better."""

    log.info("=== DAILY LEARNING ===")

    # Load today's trades
    today_trades = [t for t in state.get('trades', [])
                    if t.get('date', '').startswith(datetime.now().strftime("%Y-%m-%d"))]

    if not today_trades:
        log.info("No trades today, skipping learning")
        return None

    # Analyze
    analysis = analyze_daily_trades(today_trades)
    if not analysis:
        return None

    log.info(f"Today: {analysis['total_trades']} trades, ${analysis['daily_pnl']:.2f} P&L")

    # Propose variant
    current_config = {
        "threshold": state.get('confidence_threshold', 55),
        "cover1": -2,
        "cover2": -5,
        "current_roi": 97.41  # Known from backtest
    }

    variant = propose_strategy_variant(client, analysis, current_config)
    if not variant:
        log.warning("No variant proposed")
        return None

    log.info(f"Proposed variant: {variant['variant']}")

    # Backtest
    variant_roi = run_backtest_variant(variant)
    current_roi = current_config['current_roi']
    improvement = variant_roi - current_roi

    log.info(f"Backtest results: Current={current_roi:.2f}%, Variant={variant_roi:.2f}%, Diff={improvement:+.2f}%")

    # Deploy if >5% improvement
    if improvement > 5.0:
        log.info(f"✅ DEPLOYING VARIANT: {improvement:+.2f}% improvement")

        # Update state
        state['confidence_threshold'] = variant['config']['threshold']
        state['last_strategy_update'] = {
            "date": datetime.now().isoformat(),
            "variant": variant['variant'],
            "old_roi": current_roi,
            "new_roi": variant_roi,
            "improvement": improvement
        }

        return {
            "deployed": True,
            "variant": variant,
            "improvement": improvement
        }
    else:
        log.info(f"No significant improvement ({improvement:+.2f}%), keeping current strategy")
        return {
            "deployed": False,
            "variant": variant,
            "improvement": improvement,
            "reason": "Improvement < 5% threshold"
        }

if __name__ == '__main__':
    # Test
    logging.basicConfig(level=logging.INFO)
    client = anthropic.Anthropic()

    # Mock state
    state = {
        'trades': [],
        'confidence_threshold': 55
    }

    result = daily_learning(client, state)
    print(json.dumps(result, indent=2))
