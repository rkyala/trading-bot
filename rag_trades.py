#!/usr/bin/env python3
"""
RAG (Retrieval-Augmented Generation) for Trading
- Stores winning/losing trade patterns
- Retrieves similar past trades for context
- Helps Llama learn from history
"""

import json
import os
from datetime import datetime
from pathlib import Path

class TradeRAG:
    """Store and retrieve trading patterns"""

    def __init__(self, memory_file="trade_memory.json"):
        self.memory_file = memory_file
        self.memory = self._load_memory()

    def _load_memory(self):
        """Load or create trade memory"""
        if os.path.exists(self.memory_file):
            with open(self.memory_file, 'r') as f:
                return json.load(f)
        return {
            "winning_patterns": {},
            "losing_patterns": {},
            "total_trades": 0,
            "last_updated": None,
        }

    def _save_memory(self):
        """Persist memory"""
        self.memory["last_updated"] = datetime.now().isoformat()
        with open(self.memory_file, 'w') as f:
            json.dump(self.memory, f, indent=2)

    def record_trade(self, symbol, entry_price, exit_price, confidence, technical_context, outcome_pnl):
        """
        Record a trade for learning

        Args:
            symbol: Stock symbol
            entry_price: Entry price
            exit_price: Exit price
            confidence: Llama's confidence (0-100)
            technical_context: Dict with RSI, VWAP, etc
            outcome_pnl: Profit/loss in dollars
        """
        is_win = outcome_pnl > 0

        # Create pattern signature
        pattern = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": outcome_pnl,
            "confidence": confidence,
            "rsi": technical_context.get("rsi", None),
            "rsi_signal": technical_context.get("rsi_signal"),
            "vwap_signal": technical_context.get("vwap_signal"),
            "trend": technical_context.get("trend"),
            "distance_to_bb": technical_context.get("distance_to_upper_bb", 0),
        }

        # Store in memory
        category = "winning_patterns" if is_win else "losing_patterns"
        if symbol not in self.memory[category]:
            self.memory[category][symbol] = []

        self.memory[category][symbol].append(pattern)
        self.memory["total_trades"] += 1

        self._save_memory()

    def get_symbol_history(self, symbol):
        """Get trade history for a symbol"""
        wins = self.memory["winning_patterns"].get(symbol, [])
        losses = self.memory["losing_patterns"].get(symbol, [])
        total = len(wins) + len(losses)

        if total == 0:
            return None

        win_rate = len(wins) / total * 100 if total > 0 else 0
        avg_win_pnl = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss_pnl = sum(t["pnl"] for t in losses) / len(losses) if losses else 0

        return {
            "symbol": symbol,
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": win_rate,
            "avg_win": avg_win_pnl,
            "avg_loss": avg_loss_pnl,
            "recent_wins": wins[-3:] if wins else [],
        }

    def find_similar_patterns(self, current_rsi, current_trend, current_signal, symbol):
        """Find similar past winning patterns"""
        similar = []

        # Look at winning patterns
        for sym, patterns in self.memory["winning_patterns"].items():
            for pattern in patterns:
                # Match on: RSI zone, trend, signal type
                rsi_match = abs(pattern.get("rsi", 50) - current_rsi) < 15
                trend_match = pattern.get("trend") == current_trend
                signal_match = pattern.get("vwap_signal") == current_signal

                if rsi_match and trend_match and signal_match:
                    similar.append(pattern)

        # Sort by confidence (most confident trades first)
        similar.sort(key=lambda x: x["confidence"], reverse=True)

        return similar[:3]  # Return top 3 similar patterns

    def get_context_for_llama(self, symbol, technical_context):
        """Get RAG context to pass to Llama"""
        history = self.get_symbol_history(symbol)
        similar = self.find_similar_patterns(
            technical_context.get("rsi", 50),
            technical_context.get("trend"),
            technical_context.get("vwap_signal"),
            symbol
        )

        context = ""

        if history:
            context += f"""
TRADING HISTORY FOR {symbol}:
- Total trades: {history['total_trades']} ({history['win_rate']:.1f}% win rate)
- Average win: +${history['avg_win']:.2f}
- Average loss: -${abs(history['avg_loss']):.2f}
"""

        if similar:
            context += f"""
SIMILAR PAST WINNING PATTERNS:
"""
            for i, pattern in enumerate(similar, 1):
                context += f"""
  Pattern {i}:
  - RSI: {pattern.get('rsi', 'N/A'):.1f} ({pattern.get('rsi_signal')})
  - Trend: {pattern.get('trend')}
  - Confidence: {pattern['confidence']}%
  - Profit: +${pattern['pnl']:.2f}
"""

        return context if context else ""


# Test
if __name__ == "__main__":
    rag = TradeRAG()

    # Record sample trades
    rag.record_trade(
        symbol="MSFT",
        entry_price=480.35,
        exit_price=485.15,
        confidence=62,
        technical_context={
            "rsi": 65,
            "rsi_signal": "OVERBOUGHT",
            "vwap_signal": "ABOVE",
            "trend": "UPTREND",
        },
        outcome_pnl=4.80
    )

    # Get context
    context = rag.get_context_for_llama("MSFT", {"rsi": 68, "trend": "UPTREND", "vwap_signal": "ABOVE"})
    print("RAG Context for MSFT:")
    print(context)
