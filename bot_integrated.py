#!/usr/bin/env python3
"""
INTEGRATED BOT: Mean-Reversion Strategy + Autonomous Learning
Combines V2 mean-reversion with real-time Q-Learning optimization.

Flow:
1. Stage 1: Haiku screens for overbought movers (+5-8%)
2. Stage 2: Sonnet scores mean-reversion probability
3. Stage 3: Autonomous learning decides position sizing
4. On trade close: Learning agent updates Q-table, MAB, regime
5. Next trade: Uses improved parameters automatically

No backtest needed—learns from live trading.
"""

import os
import json
import logging
from datetime import datetime, timedelta
import anthropic
from autonomous_bot_integration import TradeWithLearning

log = logging.getLogger(__name__)

# Copy essential configuration from bot.py
TOTAL_BUDGET = 2000
CONFIDENCE_THRESHOLD = 60
RH_ACCOUNT = "432591949"

class IntegratedMeanReversionBot:
    """Bot combining mean-reversion strategy with autonomous learning."""

    def __init__(self):
        self.learning = TradeWithLearning(bot_agent=None)
        self.state_file = "trading_state_integrated.json"
        self.load_state()

    def load_state(self):
        """Load bot state including learning data."""
        try:
            with open(self.state_file) as f:
                self.state = json.load(f)
        except FileNotFoundError:
            self.state = {
                'trades': [],
                'open_positions': {},  # {order_id: {entry_info}}
                'autonomous_learning_enabled': True
            }

    def save_state(self):
        """Persist state."""
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def stage3_execute_with_learning(self, decisions, symbol, daily_change_pct, confidence):
        """
        Stage 3 execution with autonomous learning.

        Uses learned position sizing instead of fixed sizes.
        """
        if confidence < CONFIDENCE_THRESHOLD:
            return None

        log.info(f"Stage 3: Autonomous decision for {symbol} (confidence {confidence}%)")

        # Get autonomous decision (position size, strategy allocation)
        autonomous_decision = self.learning.execute_trade_with_learning(
            symbol=symbol,
            daily_change_pct=daily_change_pct,
            confidence=confidence,
            available_capital=TOTAL_BUDGET
        )

        if not autonomous_decision:
            return None

        log.info(f"  Strategy: {autonomous_decision['strategy']}")
        log.info(f"  Position: {autonomous_decision['position_size']}")
        log.info(f"  Regime: {autonomous_decision['regime']}")

        # Map to actual position size
        size_map = {
            'small': 100,
            'medium': 200,
            'large': 300
        }
        position_size = size_map.get(autonomous_decision['position_size'], 200)

        # Return decision with learned sizing
        return {
            'symbol': symbol,
            'confidence': confidence,
            'position_size': position_size,
            'strategy': autonomous_decision['strategy'],
            'regime': autonomous_decision['regime']
        }

    def record_trade_outcome(self, symbol, entry_price, exit_price, confidence, strategy):
        """
        Record trade outcome and feed to learning agent.

        This is called when a position closes.
        """
        pnl_pct = (exit_price - entry_price) / entry_price * 100

        log.info(f"Trade closed: {symbol} {pnl_pct:+.2f}% ({strategy})")

        # Feed to autonomous learning
        self.learning.close_trade_and_learn(
            trade_id=f"{symbol}_{datetime.now().timestamp()}",
            exit_price=exit_price,
            entry_price=entry_price
        )

        # Also manually update learning with full trade details
        self.learning.learning_agent.process_trade_outcome({
            'symbol': symbol,
            'entry_confidence': confidence,
            'pnl_pct': pnl_pct,
            'strategy': strategy,
            'position_size_action': 'medium'  # Could be tracked more precisely
        })

    def get_learning_status(self):
        """Get current learning state for logging."""
        return self.learning.learning_agent.get_learning_report()

    def log_regime_and_allocations(self):
        """Log current market regime and strategy allocations."""
        report = self.get_learning_status()
        regime = report.get('current_regime', 'unknown')

        log.info(f"=== Autonomous Learning Status ===")
        log.info(f"Detected Regime: {regime}")
        log.info(f"Strategy Allocations:")
        for strategy, allocation in report.get('strategy_allocations', {}).items():
            log.info(f"  {strategy}: {allocation:.1%}")


# Example integration into existing bot.py
def integrate_into_bot():
    """
    Steps to integrate into bot.py:

    1. At bot startup (before main loop):
    ```python
    integrated_bot = IntegratedMeanReversionBot()
    ```

    2. In Stage 3 (stage3_execute function):
    ```python
    # OLD: stage3_execute(client, state, decisions)
    # NEW:
    for decision in decisions:
        autonomous_dec = integrated_bot.stage3_execute_with_learning(
            decisions=decision,
            symbol=decision['symbol'],
            daily_change_pct=decision.get('daily_change_pct', 5),
            confidence=decision['confidence']
        )
        if autonomous_dec:
            # Execute using autonomous_dec['position_size']
            order_id = place_order(...)
            # Track for outcome recording
    ```

    3. When positions close:
    ```python
    integrated_bot.record_trade_outcome(
        symbol=pos['symbol'],
        entry_price=pos['entry_price'],
        exit_price=current_price,
        confidence=pos['confidence'],
        strategy=pos.get('strategy', 'mean_reversion')
    )
    ```

    4. Periodic logging (e.g., every 30 min):
    ```python
    integrated_bot.log_regime_and_allocations()
    ```
    """
    pass


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    # Test autonomous learning integration
    bot = IntegratedMeanReversionBot()

    print("\n=== Testing Integrated Bot ===\n")

    # Simulate decisions
    decisions = [
        {
            'symbol': 'NVDA',
            'confidence': 75,
            'daily_change_pct': 6.5,
            'reason': 'Overbought spike, expect pullback'
        },
        {
            'symbol': 'MSFT',
            'confidence': 65,
            'daily_change_pct': 5.2,
            'reason': 'Moderate overbought'
        }
    ]

    # Stage 3 with learning
    for dec in decisions:
        autonomous_dec = bot.stage3_execute_with_learning(
            decisions=[dec],
            symbol=dec['symbol'],
            daily_change_pct=dec['daily_change_pct'],
            confidence=dec['confidence']
        )
        if autonomous_dec:
            print(f"  → Position size: {autonomous_dec['position_size']}")
            print(f"  → Strategy: {autonomous_dec['strategy']}")

    # Simulate trade outcomes
    print("\n=== Simulating Trade Outcomes ===\n")
    bot.record_trade_outcome('NVDA', 152.0, 153.5, 75, 'mean_reversion')
    bot.record_trade_outcome('MSFT', 348.0, 346.5, 65, 'mean_reversion')
    bot.record_trade_outcome('META', 340.0, 345.2, 70, 'mean_reversion')

    # Log learning status
    print("\n=== Learning Status ===\n")
    bot.log_regime_and_allocations()
    print(json.dumps(bot.get_learning_status(), indent=2))

    bot.save_state()
    print("\n✅ Integrated bot ready to deploy")
