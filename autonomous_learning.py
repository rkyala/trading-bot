#!/usr/bin/env python3
"""
Autonomous Self-Reinforced Learning System

Uses Q-Learning + Multi-Armed Bandits to:
1. Learn position sizing from trade outcomes
2. Detect market regimes automatically
3. Allocate capital across strategies adaptively
4. Optimize for Sharpe ratio, not just ROI
"""

import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
import anthropic

log = logging.getLogger(__name__)

class MarketRegimeDetector:
    """Detect market regime (trending, mean-reverting, volatile) from recent trades."""

    def __init__(self, window=20):
        self.window = window
        self.recent_returns = []

    def add_return(self, pnl_pct):
        """Add a trade return (percentage)."""
        self.recent_returns.append(pnl_pct)
        if len(self.recent_returns) > self.window:
            self.recent_returns.pop(0)

    def detect_regime(self):
        """
        Return regime: 'trending' | 'mean_reverting' | 'volatile' | 'unknown'

        Logic:
        - trending: high win rate + consistent direction
        - mean_reverting: alternating wins/losses
        - volatile: high variance, unpredictable
        """
        if len(self.recent_returns) < 5:
            return 'unknown'

        returns = np.array(self.recent_returns)
        win_rate = len(returns[returns > 0]) / len(returns)
        volatility = np.std(returns)

        # Detect alternation (mean-reversion indicator)
        alternations = sum(1 for i in range(len(returns)-1)
                          if (returns[i] > 0) != (returns[i+1] > 0))
        alternation_ratio = alternations / (len(returns) - 1)

        if alternation_ratio > 0.6:  # Alternating wins/losses
            return 'mean_reverting'
        elif win_rate > 0.6 and volatility < 2.0:  # Consistent wins
            return 'trending'
        elif volatility > 3.0:  # High variance
            return 'volatile'
        else:
            return 'unknown'


class PositionSizer:
    """Q-Learning based position sizing: learn optimal size for each confidence level."""

    def __init__(self):
        # Q-table: q[confidence_bucket][action] = expected_return
        self.q_table = defaultdict(lambda: {'small': 0, 'medium': 0, 'large': 0})
        self.action_counts = defaultdict(lambda: {'small': 0, 'medium': 0, 'large': 0})
        self.learning_rate = 0.1
        self.discount_factor = 0.9

    def get_position_size(self, confidence, available_capital, current_regime):
        """
        Return position size: 'small' (0-1x), 'medium' (1-2x), 'large' (2-3x)

        Uses epsilon-greedy: exploit best action or explore random action.
        """
        bucket = int(confidence // 5) * 5  # Round to 5-point buckets
        epsilon = 0.1  # 10% exploration

        actions = ['small', 'medium', 'large']

        # Exploit: pick best action so far
        if np.random.random() > epsilon:
            best_action = max(actions,
                            key=lambda a: self.q_table[bucket].get(a, 0))
            return best_action

        # Explore: pick random action
        return np.random.choice(actions)

    def update(self, confidence, action, reward):
        """
        Update Q-value after trade completes.

        reward = PnL % (e.g., +1.5, -0.5)
        """
        bucket = int(confidence // 5) * 5

        # Q-learning update: Q(s,a) += α * (r + γ*max(Q(s',a')) - Q(s,a))
        old_q = self.q_table[bucket].get(action, 0)
        next_max_q = max(self.q_table[bucket].values()) if self.q_table[bucket] else 0

        new_q = old_q + self.learning_rate * (reward + self.discount_factor * next_max_q - old_q)
        self.q_table[bucket][action] = new_q
        self.action_counts[bucket][action] += 1


class StrategyAllocator:
    """
    Multi-Armed Bandit: allocate capital across strategies.

    Strategies:
    1. Momentum (buy high-confidence movers)
    2. Mean-Reversion (short overextended moves)
    3. Range-Trading (buy dips, sell rallies)
    4. Volatility (exploit high-IV opportunities)
    """

    def __init__(self):
        self.strategy_arms = {
            'momentum': {'reward_sum': 0, 'count': 0, 'allocation': 0.25},
            'mean_reversion': {'reward_sum': 0, 'count': 0, 'allocation': 0.25},
            'range_trading': {'reward_sum': 0, 'count': 0, 'allocation': 0.25},
            'volatility': {'reward_sum': 0, 'count': 0, 'allocation': 0.25},
        }
        self.alpha = 0.05  # Soft reallocation rate

    def select_strategy(self, current_regime, confidence):
        """
        Thompson Sampling: pick strategy probabilistically based on past rewards.
        Higher average reward = higher probability of selection.
        """
        if current_regime == 'trending':
            # Boost momentum strategy in trending markets
            return 'momentum'
        elif current_regime == 'mean_reverting':
            # Boost mean-reversion in choppy markets
            return 'mean_reversion'
        else:
            # Use Thompson Sampling for unknown regimes
            arms = self.strategy_arms
            expected_rewards = {}
            for strategy, stats in arms.items():
                if stats['count'] == 0:
                    expected_rewards[strategy] = 0  # Unvisited strategies
                else:
                    mean = stats['reward_sum'] / stats['count']
                    expected_rewards[strategy] = mean

            # Pick strategy with highest expected reward
            return max(expected_rewards, key=expected_rewards.get)

    def update(self, strategy, reward):
        """Update reward statistics for strategy."""
        if strategy in self.strategy_arms:
            self.strategy_arms[strategy]['reward_sum'] += reward
            self.strategy_arms[strategy]['count'] += 1

            # Soft reallocation: adjust allocation towards better performers
            self._reallocate()

    def _reallocate(self):
        """Rebalance capital allocation based on Sharpe ratios."""
        arms = self.strategy_arms

        # Calculate Sharpe for each strategy
        sharpes = {}
        for strategy, stats in arms.items():
            if stats['count'] < 2:
                sharpes[strategy] = 0
            else:
                mean = stats['reward_sum'] / stats['count']
                # Rough Sharpe (mean / stdev): we'd need variance tracking for proper Sharpe
                sharpes[strategy] = mean

        # Allocate proportional to Sharpe
        total_sharpe = sum(max(s, 0) for s in sharpes.values()) or 1
        for strategy in arms:
            target_allocation = max(sharpes[strategy], 0) / total_sharpe * 0.25
            current = arms[strategy]['allocation']
            # Gradual update towards target
            arms[strategy]['allocation'] = current * (1 - self.alpha) + target_allocation * self.alpha


class AutonomousLearningAgent:
    """Main autonomous learning loop."""

    def __init__(self, client=None):
        self.client = client or anthropic.Anthropic()
        self.regime_detector = MarketRegimeDetector()
        self.position_sizer = PositionSizer()
        self.strategy_allocator = StrategyAllocator()
        self.state_file = 'autonomous_learning_state.json'
        self.load_state()

    def load_state(self):
        """Load learned Q-table and bandit state from disk."""
        try:
            with open(self.state_file) as f:
                state = json.load(f)
                # Restore Q-table
                for bucket_str, actions in state.get('q_table', {}).items():
                    bucket = int(bucket_str)
                    self.position_sizer.q_table[bucket] = actions
                # Restore strategy rewards
                for strategy, stats in state.get('strategy_arms', {}).items():
                    if strategy in self.strategy_allocator.strategy_arms:
                        self.strategy_allocator.strategy_arms[strategy].update(stats)
        except FileNotFoundError:
            log.info("No prior learning state, starting fresh")

    def save_state(self):
        """Persist learned Q-table and strategy allocations."""
        state = {
            'q_table': {str(k): v for k, v in self.position_sizer.q_table.items()},
            'strategy_arms': self.strategy_allocator.strategy_arms,
            'timestamp': datetime.now().isoformat()
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)
        log.info("Saved autonomous learning state")

    def process_trade_outcome(self, trade):
        """
        Called after each trade closes. Reinforces learning.

        trade = {
            'symbol': 'NVDA',
            'entry_confidence': 75,
            'pnl_pct': 1.5,
            'strategy': 'momentum',
            'position_size_action': 'medium'
        }
        """
        log.info(f"Learning from trade: {trade['symbol']} {trade['pnl_pct']:+.2f}% ({trade['strategy']})")

        # Add to regime detector
        self.regime_detector.add_return(trade['pnl_pct'])

        # Update position sizer Q-table
        self.position_sizer.update(
            trade['entry_confidence'],
            trade['position_size_action'],
            trade['pnl_pct']
        )

        # Update strategy allocator
        self.strategy_allocator.update(
            trade['strategy'],
            trade['pnl_pct']
        )

        # Save state periodically
        self.save_state()

    def decide_trade_parameters(self, symbol, daily_change_pct, confidence):
        """
        Claude-free decision: use learned models to decide trade params.

        Returns: {
            'strategy': 'momentum' | 'mean_reversion' | 'range_trading' | 'volatility',
            'position_size': 'small' | 'medium' | 'large',
            'entry_reason': 'high confidence momentum' | 'mean-reversion setup' | etc.
        }
        """
        current_regime = self.regime_detector.detect_regime()
        strategy = self.strategy_allocator.select_strategy(current_regime, confidence)
        position_size = self.position_sizer.get_position_size(
            confidence,
            available_capital=2000,  # TODO: pass actual
            current_regime=current_regime
        )

        return {
            'strategy': strategy,
            'position_size': position_size,
            'regime': current_regime,
            'entry_reason': f'{strategy} ({current_regime}), confidence={confidence}%'
        }

    def get_learning_report(self):
        """Generate summary of learned parameters for logging."""
        regime = self.regime_detector.detect_regime()

        report = {
            'current_regime': regime,
            'position_sizer_q_table': dict(self.position_sizer.q_table),
            'strategy_allocations': {
                k: v['allocation'] for k, v in self.strategy_allocator.strategy_arms.items()
            },
            'strategy_performance': {
                k: {
                    'avg_reward': v['reward_sum'] / v['count'] if v['count'] > 0 else 0,
                    'trades': v['count']
                }
                for k, v in self.strategy_allocator.strategy_arms.items()
            }
        }

        return report


def daily_learning_summary(agent):
    """Generate Claude-assisted insight on learned behavior."""
    report = agent.get_learning_report()

    prompt = f"""Based on today's autonomous learning, provide a 2-sentence insight:

Learning Report:
{json.dumps(report, indent=2)}

Focus on: What did the bot learn about the market? What strategy is working best?
"""

    try:
        resp = anthropic.Anthropic().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.content[0].text
    except Exception as e:
        log.error(f"Failed to generate learning summary: {e}")
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    agent = AutonomousLearningAgent()

    # Simulate trades
    trades = [
        {'symbol': 'NVDA', 'entry_confidence': 75, 'pnl_pct': 1.5, 'strategy': 'momentum', 'position_size_action': 'medium'},
        {'symbol': 'MSFT', 'entry_confidence': 60, 'pnl_pct': -0.5, 'strategy': 'momentum', 'position_size_action': 'medium'},
        {'symbol': 'TSLA', 'entry_confidence': 80, 'pnl_pct': 2.1, 'strategy': 'momentum', 'position_size_action': 'large'},
        {'symbol': 'META', 'entry_confidence': 55, 'pnl_pct': 0.8, 'strategy': 'mean_reversion', 'position_size_action': 'small'},
    ]

    for trade in trades:
        agent.process_trade_outcome(trade)

    print("\nLearning Report:")
    print(json.dumps(agent.get_learning_report(), indent=2))
