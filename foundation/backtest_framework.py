"""
Foundation Backtest Engine - Core Trade Execution Logic
Manages trade lifecycle, metrics calculation, and position tracking

Day 1 Component: Orchestrates all 6 Foundation components
Success Metric: Win rate >= 55%, Profit factor > 1.5 on 180-day backtest
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Represents a single completed trade"""
    symbol: str
    entry_price: float
    entry_time: datetime
    exit_price: float
    exit_time: datetime
    qty: int
    stop_loss: float
    target: float
    pnl: float  # Absolute P&L
    pnl_pct: float  # Percentage P&L
    exit_reason: str  # "stop_loss", "target", "manual_close"

    def to_dict(self):
        """Convert to dict for CSV export"""
        return {
            'symbol': self.symbol,
            'entry_price': round(self.entry_price, 2),
            'entry_time': self.entry_time.isoformat(),
            'exit_price': round(self.exit_price, 2),
            'exit_time': self.exit_time.isoformat(),
            'qty': self.qty,
            'stop_loss': round(self.stop_loss, 2),
            'target': round(self.target, 2),
            'pnl': round(self.pnl, 2),
            'pnl_pct': round(self.pnl_pct, 4),
            'exit_reason': self.exit_reason
        }


@dataclass
class Position:
    """Represents an active position"""
    symbol: str
    qty: int
    entry_price: float
    entry_time: datetime
    stop_loss: float
    target: float
    highest_price: float  # For trailing stop
    cycles_held: int  # Number of cycles position held


class BacktestEngine:
    """
    Complete Foundation backtest orchestrator

    Responsibilities:
    1. Execute trades based on signals + all 6 Foundation components
    2. Track entries and exits with proper P&L calculation
    3. Calculate success metrics (win rate, profit factor, etc.)
    4. Handle position management (stops, targets, exits)
    """

    def __init__(self, initial_capital: float = 10000, position_size_pct: float = 0.015):
        self.capital = initial_capital
        self.position_size_pct = position_size_pct
        self.current_balance = initial_capital
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        self.equity_curve = [initial_capital]
        self.timestamps = []

    def calculate_position_size(self, symbol: str, entry_price: float) -> int:
        """
        Calculate position quantity based on account size

        Returns qty that respects 1.5% position size cap
        """
        max_position_value = self.current_balance * self.position_size_pct  # 1.5% of balance
        qty = max(1, int(max_position_value / entry_price))

        # Hard cap: never exceed $150 per position (0.5% safety margin)
        hard_cap = int((self.current_balance * 0.005) / entry_price)
        qty = min(qty, hard_cap)

        return qty

    def enter_trade(self, symbol: str, entry_price: float,
                   stop_loss: float, target: float,
                   entry_time: datetime) -> bool:
        """
        Enter a new position

        Returns True if entry successful, False if rejected
        """
        if symbol in self.positions:
            logger.warning(f"[{symbol}] Already have active position, skipping")
            return False

        qty = self.calculate_position_size(symbol, entry_price)

        position = Position(
            symbol=symbol,
            qty=qty,
            entry_price=entry_price,
            entry_time=entry_time,
            stop_loss=stop_loss,
            target=target,
            highest_price=entry_price,
            cycles_held=0
        )

        self.positions[symbol] = position
        logger.info(f"✅ ENTRY: {symbol} @ ${entry_price:.2f} x{qty} | SL: ${stop_loss:.2f} | TGT: ${target:.2f}")
        return True

    def exit_trade(self, symbol: str, exit_price: float,
                  exit_time: datetime, reason: str) -> bool:
        """
        Exit an active position and record trade

        Returns True if exit successful
        """
        if symbol not in self.positions:
            logger.warning(f"[{symbol}] No active position to exit")
            return False

        position = self.positions[symbol]

        # Calculate P&L
        pnl = (exit_price - position.entry_price) * position.qty
        pnl_pct = (exit_price - position.entry_price) / position.entry_price

        # Update balance
        self.current_balance += pnl

        # Record trade
        trade = Trade(
            symbol=symbol,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            exit_price=exit_price,
            exit_time=exit_time,
            qty=position.qty,
            stop_loss=position.stop_loss,
            target=position.target,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason
        )

        self.trades.append(trade)
        del self.positions[symbol]

        logger.info(f"❌ EXIT: {symbol} @ ${exit_price:.2f} | P&L: ${pnl:.2f} ({pnl_pct*100:.2f}%) | Reason: {reason}")
        return True

    def check_position_exit(self, symbol: str, current_price: float,
                           current_time: datetime) -> Optional[str]:
        """
        Check if position should exit (stop hit or target hit)

        Returns: "stop_loss", "target", or None
        """
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        # Update highest price (for trailing stop)
        position.highest_price = max(position.highest_price, current_price)

        # Check stop loss
        if current_price <= position.stop_loss:
            return "stop_loss"

        # Check target
        if current_price >= position.target:
            return "target"

        return None

    def increment_cycle_count(self):
        """Increment cycles_held for all active positions"""
        for symbol in self.positions:
            self.positions[symbol].cycles_held += 1

    def calculate_metrics(self) -> Dict:
        """
        Calculate success metrics for backtest validation

        Returns:
            {
                'total_trades': int,
                'win_rate': float (0-100),
                'profit_factor': float,
                'avg_win': float,
                'avg_loss': float,
                'max_drawdown': float,
                'total_pnl': float,
                'sharpe_ratio': float
            }
        """
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'profit_factor': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'max_drawdown': 0,
                'total_pnl': 0,
                'sharpe_ratio': 0
            }

        # Basic metrics
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)

        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0

        # Win/Loss amounts
        total_wins = sum(t.pnl for t in winning_trades)
        total_losses = abs(sum(t.pnl for t in losing_trades))

        avg_win = (total_wins / win_count) if win_count > 0 else 0
        avg_loss = -(total_losses / loss_count) if loss_count > 0 else 0

        # Profit factor
        profit_factor = (total_wins / total_losses) if total_losses > 0 else 0

        # Total P&L
        total_pnl = sum(t.pnl for t in self.trades)

        # Max drawdown
        max_drawdown = self._calculate_max_drawdown()

        # Sharpe ratio
        sharpe_ratio = self._calculate_sharpe_ratio()

        return {
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_drawdown': max_drawdown,
            'total_pnl': total_pnl,
            'sharpe_ratio': sharpe_ratio
        }

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown percentage from peak"""
        if not self.trades:
            return 0

        equity = self.capital
        peak = self.capital
        max_dd = 0

        for trade in self.trades:
            equity += trade.pnl
            if equity > peak:
                peak = equity
            else:
                dd = (peak - equity) / peak * 100
                max_dd = max(max_dd, dd)

        return max_dd

    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio (annual)
        Assumes 252 trading days
        """
        if not self.trades or len(self.trades) < 2:
            return 0

        returns = [t.pnl_pct for t in self.trades]
        mean_return = np.mean(returns) * 252  # Annualize
        std_return = np.std(returns) * np.sqrt(252)

        if std_return == 0:
            return 0

        sharpe = (mean_return - risk_free_rate) / std_return
        return sharpe

    def export_trades_csv(self, filename: str = 'backtest_trades.csv'):
        """Export all trades to CSV"""
        if not self.trades:
            logger.warning("No trades to export")
            return

        df = pd.DataFrame([t.to_dict() for t in self.trades])
        df.to_csv(filename, index=False)
        logger.info(f"✅ Exported {len(self.trades)} trades to {filename}")

    def print_summary(self):
        """Print backtest summary to console"""
        metrics = self.calculate_metrics()

        print("\n" + "="*60)
        print("BACKTEST SUMMARY")
        print("="*60)
        print(f"Initial Capital:     ${self.capital:,.2f}")
        print(f"Final Balance:       ${self.current_balance:,.2f}")
        print(f"Total P&L:           ${metrics['total_pnl']:,.2f}")
        print(f"Total Trades:        {metrics['total_trades']}")
        print(f"  - Winners:        {metrics['win_count']} ({metrics['win_rate']:.1f}%)")
        print(f"  - Losers:         {metrics['loss_count']}")
        print(f"Avg Win:             ${metrics['avg_win']:.2f}")
        print(f"Avg Loss:            ${metrics['avg_loss']:.2f}")
        print(f"Profit Factor:       {metrics['profit_factor']:.2f}")
        print(f"Max Drawdown:        {metrics['max_drawdown']:.2f}%")
        print(f"Sharpe Ratio:        {metrics['sharpe_ratio']:.2f}")
        print("="*60 + "\n")

        # Gate 1 validation
        pass_gate1 = (
            metrics['win_rate'] >= 55 and
            metrics['profit_factor'] > 1.5 and
            metrics['total_trades'] >= 40
        )

        print(f"Gate 1 Status: {'✅ PASSED' if pass_gate1 else '❌ FAILED'}")
        print(f"  Win Rate >= 55%:         {metrics['win_rate']:.1f}% {'✅' if metrics['win_rate'] >= 55 else '❌'}")
        print(f"  Profit Factor > 1.5:     {metrics['profit_factor']:.2f} {'✅' if metrics['profit_factor'] > 1.5 else '❌'}")
        print(f"  Total Trades >= 40:      {metrics['total_trades']} {'✅' if metrics['total_trades'] >= 40 else '❌'}")
        print()
