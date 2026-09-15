#!/usr/bin/env python3
"""
Exit Strategy Manager
Handles position exits with profit targets, stop losses, and risk management
"""

import json
import logging
from datetime import datetime, timedelta
import yfinance as yf

log = logging.getLogger(__name__)

class ExitStrategy:
    """Manages trade exits and position management"""

    def __init__(self):
        self.positions = {}  # Track open positions
        self.closed_trades = []  # Track closed trades

    def load_positions(self):
        """Load open positions from Robinhood"""
        try:
            # TODO: Integrate with Robinhood MCP
            # get_equity_positions() -> returns list of open positions
            # For now, return empty dict for dry-run
            return {}
        except Exception as e:
            log.error(f"Error loading positions: {e}")
            return {}

    def open_position(self, symbol, entry_price, position_size=600):
        """Record a new open position"""
        self.positions[symbol] = {
            "entry_price": entry_price,
            "position_size": position_size,
            "entry_time": datetime.now(),
            "entry_value": entry_price * (position_size / entry_price),
            "status": "open"
        }
        log.info(f"Position opened: {symbol} @ ${entry_price:.2f}")

    def check_exit(self, symbol, current_price):
        """Check if position should be exited"""
        if symbol not in self.positions:
            return None, None

        pos = self.positions[symbol]
        entry_price = pos["entry_price"]
        entry_time = pos["entry_time"]
        pnl = ((current_price - entry_price) / entry_price) * 100
        holding_time = (datetime.now() - entry_time).total_seconds() / 3600  # hours

        # ===== EXIT CONDITIONS =====

        # 1. PROFIT TARGET (+1.5%)
        if pnl >= 1.5:
            return "profit_target", f"+{pnl:.2f}% (target: +1.5%)"

        # 2. STOP LOSS (-1.5%)
        if pnl <= -1.5:
            return "stop_loss", f"{pnl:.2f}% (stop: -1.5%)"

        # 3. TIME-BASED EXIT (held > 4 hours)
        if holding_time > 4:
            return "time_exit", f"Held {holding_time:.1f} hours (max: 4h)"

        # 4. TRAILING STOP (if profit, protect with 0.5% trail)
        if pnl > 0.5:
            trailing_stop = entry_price * 1.005  # 0.5% below peak
            if current_price < trailing_stop:
                return "trailing_stop", f"Trail hit at {pnl:.2f}%"

        # 5. VOLATILITY EXIT (if price swings >3% in hour)
        # TODO: Implement intra-hour volatility check

        return None, None

    def close_position(self, symbol, exit_price, exit_reason):
        """Close a position and record the trade"""
        if symbol not in self.positions:
            log.warning(f"Position {symbol} not found")
            return None

        pos = self.positions[symbol]
        entry_price = pos["entry_price"]
        position_size = pos["position_size"]

        # Calculate P&L
        pnl_dollars = (exit_price - entry_price) * (position_size / entry_price)
        pnl_percent = ((exit_price - entry_price) / entry_price) * 100
        holding_time = (datetime.now() - pos["entry_time"]).total_seconds() / 3600

        # Record closed trade
        closed_trade = {
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "position_size": position_size,
            "entry_time": pos["entry_time"].isoformat(),
            "exit_time": datetime.now().isoformat(),
            "holding_hours": holding_time,
            "pnl_dollars": pnl_dollars,
            "pnl_percent": pnl_percent,
            "exit_reason": exit_reason
        }

        self.closed_trades.append(closed_trade)

        # Remove from open positions
        del self.positions[symbol]

        log.info(
            f"Position closed: {symbol} "
            f"Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f} "
            f"P&L: ${pnl_dollars:.2f} ({pnl_percent:+.2f}%) "
            f"Reason: {exit_reason}"
        )

        return closed_trade

    def get_daily_summary(self):
        """Get summary of today's closed trades"""
        if not self.closed_trades:
            return {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl": 0,
                "win_rate": 0,
                "avg_pnl": 0
            }

        trades = self.closed_trades
        wins = [t for t in trades if t["pnl_dollars"] > 0]
        losses = [t for t in trades if t["pnl_dollars"] < 0]
        total_pnl = sum(t["pnl_dollars"] for t in trades)
        avg_pnl = total_pnl / len(trades) if trades else 0
        win_rate = (len(wins) / len(trades) * 100) if trades else 0

        return {
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "trades_detail": trades
        }

    def save_trades_log(self, filename="closed_trades.json"):
        """Save closed trades to file"""
        try:
            with open(filename, "w") as f:
                json.dump(self.closed_trades, f, indent=2, default=str)
            log.info(f"Saved {len(self.closed_trades)} closed trades to {filename}")
        except Exception as e:
            log.error(f"Error saving trades: {e}")

    def print_summary(self):
        """Print trade summary"""
        summary = self.get_daily_summary()

        log.info("\n" + "="*80)
        log.info("TRADE SUMMARY")
        log.info("="*80)
        log.info(f"Total Trades: {summary['trades']}")
        log.info(f"Wins: {summary['wins']} | Losses: {summary['losses']}")
        log.info(f"Win Rate: {summary['win_rate']:.1f}%")
        log.info(f"Total P&L: ${summary['total_pnl']:.2f}")
        log.info(f"Avg P&L per trade: ${summary['avg_pnl']:.2f}")
        log.info("="*80 + "\n")


# ============================================================================
# EXIT STRATEGY CONFIGURATIONS
# ============================================================================

class ConservativeExit(ExitStrategy):
    """Conservative: tighter stops, faster exits"""
    # Profit target: +1.0%
    # Stop loss: -1.0%
    # Time exit: 2 hours
    pass

class AggresiveExit(ExitStrategy):
    """Aggressive: wider stops, hold longer"""
    # Profit target: +2.0%
    # Stop loss: -2.0%
    # Time exit: 6 hours
    pass

class MeanReversionExit(ExitStrategy):
    """Optimized for mean-reversion strategy"""
    # Profit target: +1.5% (pullback fully retraces)
    # Stop loss: -2.0% (mean-reversion failed)
    # Time exit: 4 hours
    # Trailing stop: +0.5% after profit
    pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test exit strategy
    exit_mgr = MeanReversionExit()

    # Simulate position
    exit_mgr.open_position("AAPL", 150.00)

    # Simulate price movement
    print("\nTest 1: Profit target hit")
    reason, details = exit_mgr.check_exit("AAPL", 152.25)  # +1.5%
    if reason:
        exit_mgr.close_position("AAPL", 152.25, reason)

    # Simulate another position
    print("\nTest 2: Stop loss hit")
    exit_mgr.open_position("MSFT", 300.00)
    reason, details = exit_mgr.check_exit("MSFT", 295.50)  # -1.5%
    if reason:
        exit_mgr.close_position("MSFT", 295.50, reason)

    # Summary
    exit_mgr.print_summary()
