#!/usr/bin/env python3
"""
Integration layer: Connect autonomous learning agent to trading bot.

This replaces the old backtest-based learning.py with real-time learning.
"""

import json
import logging
from datetime import datetime
import anthropic
from autonomous_learning import AutonomousLearningAgent

log = logging.getLogger(__name__)


class TradeWithLearning:
    """Wraps trade execution to capture learning signals."""

    def __init__(self, bot_agent):
        self.bot_agent = bot_agent
        self.learning_agent = AutonomousLearningAgent()
        self.active_trades = {}  # symbol -> trade_state

    def execute_trade_with_learning(self, symbol, daily_change_pct, confidence, available_capital):
        """
        Execute trade with autonomous learning decision-making.

        BEFORE: Bot uses fixed thresholds and parameters
        NOW: Uses learned position sizing and strategy selection

        Returns: decision (or None if skipped)
        """
        # Get autonomous decision (no backtest needed)
        decision = self.learning_agent.decide_trade_parameters(
            symbol=symbol,
            daily_change_pct=daily_change_pct,
            confidence=confidence
        )

        log.info(f"[AUTONOMOUS] {symbol}: {decision['entry_reason']}")
        log.info(f"  Strategy: {decision['strategy']}")
        log.info(f"  Position: {decision['position_size']}")
        log.info(f"  Regime: {decision['regime']}")

        # Map autonomous decision to concrete position size
        size_map = {'small': 100, 'medium': 250, 'large': 500}
        position_size = size_map[decision['position_size']]

        # Execute trade (same as before)
        trade_id = self._execute_actual_trade(
            symbol=symbol,
            position_size=position_size,
            entry_confidence=confidence,
            strategy=decision['strategy']
        )

        if trade_id:
            # Track for learning
            self.active_trades[trade_id] = {
                'symbol': symbol,
                'entry_confidence': confidence,
                'strategy': decision['strategy'],
                'position_size_action': decision['position_size'],
                'entry_time': datetime.now()
            }

        return decision

    def close_trade_and_learn(self, trade_id, exit_price, entry_price):
        """
        Close position and immediately feed outcome to learning agent.

        This is the KEY difference: real-time learning, not daily batched analysis.
        """
        if trade_id not in self.active_trades:
            return

        trade = self.active_trades[trade_id]
        pnl_pct = (exit_price - entry_price) / entry_price * 100

        # Reinforce learning
        self.learning_agent.process_trade_outcome({
            'symbol': trade['symbol'],
            'entry_confidence': trade['entry_confidence'],
            'pnl_pct': pnl_pct,
            'strategy': trade['strategy'],
            'position_size_action': trade['position_size_action']
        })

        log.info(f"[LEARNED] {trade['symbol']}: {pnl_pct:+.2f}% "
                f"({trade['strategy']}, {trade['position_size_action']})")

        del self.active_trades[trade_id]

    def _execute_actual_trade(self, symbol, position_size, entry_confidence, strategy):
        """
        Execute actual buy/sell via MCP.
        (Same as bot.py, returns trade_id)
        """
        # TODO: Call MCP place_equity_order here
        # For now, just return a mock ID
        return f"{symbol}_{datetime.now().timestamp()}"

    def get_learning_status(self):
        """Return learning agent status for logging."""
        return self.learning_agent.get_learning_report()


# Integration with Stage 3 (auto-execute)
def stage3_execute_with_learning(decision_from_stage2, confidence, symbol, learning_integration):
    """
    Stage 3: Use autonomous learning to decide position size/strategy.

    BEFORE: Fixed parameters (e.g., max 500 shares, always same strat)
    NOW: Adaptive based on what's working

    Args:
        decision_from_stage2: dict from Claude Sonnet (buy/sell signal)
        confidence: confidence score (55-85%)
        symbol: stock symbol
        learning_integration: TradeWithLearning instance

    Returns:
        order_id or None
    """
    daily_change = decision_from_stage2.get('daily_change_pct', 5)

    # Get autonomous decision
    autonomous_decision = learning_integration.execute_trade_with_learning(
        symbol=symbol,
        daily_change_pct=daily_change,
        confidence=confidence,
        available_capital=2000  # TODO: get from account
    )

    if not autonomous_decision:
        return None

    # Place actual order
    log.info(f"Stage 3: Executing {symbol} with learned parameters")
    # order_id = place_order(symbol, size, side)
    # return order_id

    return "order_pending"


# New daily report: learning insights instead of variant backtests
def daily_learning_report(learning_integration):
    """
    Replace old learning.py's variant proposal with learning insights.

    OLD: "Propose threshold change from 55→65, backtest shows +3% improvement"
    NEW: "Learned position sizing: large sizes work best for 75+ confidence.
           Mean reversion strategy outperforming momentum in choppy conditions."
    """
    report = learning_integration.get_learning_status()

    prompt = f"""Summarize today's autonomous learning in 3 bullets:

{json.dumps(report, indent=2)}

Focus on:
1. Which strategies performed best
2. What market regime was detected
3. How position sizing evolved
"""

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text
    except Exception as e:
        log.error(f"Failed to generate learning report: {e}")
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Mock bot agent
    class MockBot:
        pass

    learning = TradeWithLearning(MockBot())

    # Simulate trades
    print("=== Simulating Autonomous Learning ===\n")

    # Trade 1: Momentum works
    decision = learning.execute_trade_with_learning('NVDA', 5.2, 75, 2000)
    learning.close_trade_and_learn('NVDA_1', 150, 147.5)  # +1.67%

    # Trade 2: Momentum fails
    decision = learning.execute_trade_with_learning('MSFT', 4.1, 60, 2000)
    learning.close_trade_and_learn('MSFT_1', 348, 351)  # -0.86%

    # Trade 3: Mean-reversion works
    decision = learning.execute_trade_with_learning('TSLA', 6.3, 65, 2000)
    learning.close_trade_and_learn('TSLA_1', 245, 243)  # +0.82%

    print("\n=== Learning Status ===")
    print(json.dumps(learning.get_learning_status(), indent=2))

    print("\n=== Daily Report ===")
    report = daily_learning_report(learning)
    if report:
        print(report)
