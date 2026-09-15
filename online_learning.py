#!/usr/bin/env python3
"""
Online Learning: Adapt Llama confidence thresholds based on trade performance
- Tracks win rate by symbol
- Adjusts confidence threshold dynamically
- Lowers threshold if Llama underperforming
- Raises threshold if Llama overconfident
"""

import json
import os
from datetime import datetime
from collections import defaultdict

class OnlineLearner:
    """Adapt trading thresholds based on real trade outcomes"""

    def __init__(self, metrics_file="trade_performance.json"):
        self.metrics_file = metrics_file
        self.metrics = self._load_metrics()

    def _load_metrics(self):
        """Load accumulated trade performance metrics"""
        if os.path.exists(self.metrics_file):
            with open(self.metrics_file, 'r') as f:
                data = json.load(f)
                # Convert back to defaultdicts
                trades_dict = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
                trades_dict.update(data.get("trades_by_symbol", {}))

                adj_dict = defaultdict(lambda: 0)
                adj_dict.update(data.get("confidence_adjustments", {}))

                return {
                    "trades_by_symbol": trades_dict,
                    "confidence_adjustments": adj_dict,
                    "last_updated": data.get("last_updated"),
                }
        return {
            "trades_by_symbol": defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0}),
            "confidence_adjustments": defaultdict(lambda: 0),
            "last_updated": None,
        }

    def _save_metrics(self):
        """Persist metrics to file"""
        metrics_to_save = {
            "trades_by_symbol": {k: dict(v) for k, v in self.metrics["trades_by_symbol"].items()},
            "confidence_adjustments": dict(self.metrics["confidence_adjustments"]),
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.metrics_file, 'w') as f:
            json.dump(metrics_to_save, f, indent=2)

    def record_trade_result(self, symbol, llama_confidence, actual_result):
        """
        Record a trade outcome to learn from

        Args:
            symbol (str): Stock symbol (e.g., "MSFT")
            llama_confidence (int): Llama's confidence (0-100)
            actual_result (float): Trade P&L in dollars (+profit or -loss)
        """
        is_win = actual_result > 0

        # Track performance
        trades = self.metrics["trades_by_symbol"][symbol]
        trades["wins"] += 1 if is_win else 0
        trades["losses"] += 0 if is_win else 1
        trades["total"] += 1

        # Store detailed record
        if "history" not in trades:
            trades["history"] = []
        trades["history"].append({
            "timestamp": datetime.now().isoformat(),
            "llama_confidence": llama_confidence,
            "result": actual_result,
            "win": is_win,
        })

        self._save_metrics()

    def get_adaptive_threshold(self, symbol, base_threshold=60):
        """
        Calculate adaptive confidence threshold based on win rate

        Returns:
            int: Adjusted threshold (lower if Llama underperforming, higher if overconfident)
        """
        trades = self.metrics["trades_by_symbol"].get(symbol, {})
        total = trades.get("total", 0)

        if total < 1:  # Need minimum sample size (1 for dry-run testing, 5 for production)
            return base_threshold

        win_rate = trades.get("wins", 0) / total

        # Adjust threshold based on win rate
        if win_rate >= 0.65:
            # Llama is performing well → lower threshold to trade more
            adjustment = -5
        elif win_rate >= 0.55:
            # Llama is good → keep as is
            adjustment = 0
        elif win_rate >= 0.45:
            # Llama is poor → raise threshold to be more selective
            adjustment = +10
        else:
            # Llama is very poor → much higher threshold
            adjustment = +20

        self.metrics["confidence_adjustments"][symbol] = adjustment
        self._save_metrics()

        return max(50, min(75, base_threshold + adjustment))  # Clamp between 50-75%

    def get_win_rate(self, symbol):
        """Get win rate for a symbol"""
        trades = self.metrics["trades_by_symbol"].get(symbol, {})
        total = trades.get("total", 0)

        if total == 0:
            return None

        return trades.get("wins", 0) / total

    def print_summary(self):
        """Print performance summary"""
        print("\n" + "="*80)
        print("ONLINE LEARNING SUMMARY")
        print("="*80)

        for symbol, trades in sorted(self.metrics["trades_by_symbol"].items()):
            total = trades.get("total", 0)
            wins = trades.get("wins", 0)

            if total > 0:
                win_rate = (wins / total) * 100
                adjustment = self.metrics["confidence_adjustments"].get(symbol, 0)
                adaptive_threshold = 60 + adjustment

                print(f"\n{symbol}:")
                print(f"  Trades: {total} ({wins}W / {total - wins}L)")
                print(f"  Win Rate: {win_rate:.1f}%")
                print(f"  Confidence Adjustment: {adjustment:+d}% → Threshold: {adaptive_threshold}%")

        print("\n" + "="*80 + "\n")


# Test usage
if __name__ == "__main__":
    learner = OnlineLearner()

    # Example: Record some trades
    learner.record_trade_result("MSFT", 62, +14.41)  # Win
    learner.record_trade_result("MSFT", 50, -7.21)   # Loss
    learner.record_trade_result("NVDA", 50, +9.60)   # Win

    # Get adaptive thresholds
    msft_threshold = learner.get_adaptive_threshold("MSFT")
    nvda_threshold = learner.get_adaptive_threshold("NVDA")

    print(f"MSFT adaptive threshold: {msft_threshold}%")
    print(f"NVDA adaptive threshold: {nvda_threshold}%")

    learner.print_summary()
