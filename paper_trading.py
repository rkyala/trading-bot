#!/usr/bin/env python3
"""
Paper Trading Engine
Runs FinRL agent in simulation mode (no real orders)
Tracks portfolio P&L and generates daily reports
"""

import os
import json
import logging
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from stable_baselines3 import PPO
import pickle

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

SYMBOLS = [
    "INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS", "AMAT", "TXN", "ADI",
    "CSCO", "ENPH", "JPM", "SNPS", "CRM", "NOW", "MSFT", "CDNS", "IBM",
    "BA", "MCD", "CAT", "PG", "HD", "MA", "V", "GS", "BAC"
]

INITIAL_AMOUNT = 10000
MAX_POSITION = 1500
MODEL_PATH = "trained_ppo_agent"
PAPER_TRADING_LOG = "paper_trading_log.csv"
DAILY_REPORT_DIR = "paper_trading_reports"

os.makedirs(DAILY_REPORT_DIR, exist_ok=True)

# ============================================================================
# PAPER TRADING ENGINE
# ============================================================================

class PaperTradingEngine:
    """Simulates trading without real orders"""

    def __init__(self, initial_amount=10000, max_position=1500):
        self.initial_amount = initial_amount
        self.max_position = max_position
        self.symbols = SYMBOLS

        # Load trained model
        try:
            self.model = PPO.load(MODEL_PATH)
            log.info(f"✓ Loaded trained model from {MODEL_PATH}")
        except Exception as e:
            log.error(f"✗ Failed to load model: {e}")
            raise

        # Portfolio state
        self.cash = initial_amount
        self.positions = {s: 0 for s in self.symbols}  # shares held
        self.entry_prices = {s: 0 for s in self.symbols}
        self.entry_dates = {s: None for s in self.symbols}

        # History
        self.trades = []  # List of executed trades
        self.daily_values = []  # Daily portfolio values
        self.current_date = None

    def get_current_prices(self):
        """Fetch current/latest prices"""
        prices = {}
        for symbol in self.symbols:
            try:
                ticker = yf.Ticker(symbol)
                data = ticker.history(period='1d')
                if not data.empty:
                    prices[symbol] = float(data['Close'].iloc[-1])
                else:
                    prices[symbol] = None
            except:
                prices[symbol] = None

        return prices

    def get_state_vector(self, prices, market_data=None):
        """Build state vector for model"""
        state = []

        # Portfolio value
        portfolio_value = self.cash + sum(
            self.positions[s] * prices.get(s, 0) for s in self.symbols if prices.get(s)
        )
        state.append(self.cash / self.initial_amount)

        # For each stock
        for s in self.symbols:
            price = prices.get(s, 0)
            if price and price > 0:
                # Price change
                state.append(0)  # Placeholder, would need history

                # RSI (placeholder)
                state.append(0.5)

                # Position
                state.append(self.positions[s] * price / self.max_position)

                # Unrealized P&L
                if self.positions[s] > 0:
                    pnl = (price - self.entry_prices[s]) / self.entry_prices[s] if self.entry_prices[s] > 0 else 0
                    state.append(pnl)
                else:
                    state.append(0)
            else:
                state.extend([0, 0.5, 0, 0])

        return np.array(state[:4 * len(self.symbols) + 1], dtype=np.float32)

    def step(self, prices):
        """Execute one step: get agent decision and update portfolio"""
        # Get state
        state = self.get_state_vector(prices)

        # Get agent action
        try:
            action, _ = self.model.predict(state, deterministic=True)
        except:
            log.warning("Model prediction failed, holding positions")
            return

        # Decode actions (simplified: 0=hold, 1=buy, 2=sell per stock)
        for i, symbol in enumerate(self.symbols):
            price = prices.get(symbol, 0)
            if not price or price <= 0:
                continue

            action_val = int(action) if isinstance(action, (int, float)) else 0

            if action_val == 1:  # BUY signal
                if self.cash >= self.max_position * 0.1 and self.positions[symbol] == 0:
                    qty = min(
                        self.max_position / price,
                        self.cash / price * 0.9  # Keep 10% cash reserve
                    )

                    if qty > 0.1:  # Only execute if meaningful qty
                        cost = qty * price
                        self.cash -= cost
                        self.positions[symbol] = qty
                        self.entry_prices[symbol] = price
                        self.entry_dates[symbol] = self.current_date

                        self.trades.append({
                            'date': self.current_date,
                            'symbol': symbol,
                            'action': 'BUY',
                            'price': price,
                            'quantity': qty,
                            'cost': cost
                        })

                        log.debug(f"  BUY {qty:.2f} {symbol} @ ${price:.2f}")

            elif action_val == 2:  # SELL signal
                if self.positions[symbol] > 0:
                    qty = self.positions[symbol]
                    proceeds = qty * price
                    pnl = proceeds - (qty * self.entry_prices[symbol])
                    pnl_pct = (price - self.entry_prices[symbol]) / self.entry_prices[symbol]

                    self.cash += proceeds
                    self.positions[symbol] = 0

                    self.trades.append({
                        'date': self.current_date,
                        'symbol': symbol,
                        'action': 'SELL',
                        'price': price,
                        'quantity': qty,
                        'proceeds': proceeds,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct
                    })

                    log.debug(f"  SELL {qty:.2f} {symbol} @ ${price:.2f} (P&L: {pnl_pct:+.2f}%)")

    def get_portfolio_value(self, prices):
        """Calculate total portfolio value"""
        value = self.cash
        for symbol in self.symbols:
            price = prices.get(symbol, 0)
            if price and price > 0:
                value += self.positions[symbol] * price

        return value

    def get_daily_report(self, prices):
        """Generate daily report"""
        portfolio_value = self.get_portfolio_value(prices)
        total_pnl = portfolio_value - self.initial_amount
        total_pnl_pct = (total_pnl / self.initial_amount) * 100

        # Calculate Sharpe ratio (simplified)
        if len(self.daily_values) > 1:
            returns = np.diff(self.daily_values) / self.daily_values[:-1]
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
        else:
            sharpe = 0

        # Get top holdings
        holdings = []
        for symbol in self.symbols:
            price = prices.get(symbol, 0)
            if self.positions[symbol] > 0 and price > 0:
                value = self.positions[symbol] * price
                pnl_pct = (price - self.entry_prices[symbol]) / self.entry_prices[symbol] * 100
                holdings.append({
                    'symbol': symbol,
                    'shares': self.positions[symbol],
                    'price': price,
                    'value': value,
                    'entry_price': self.entry_prices[symbol],
                    'pnl_pct': pnl_pct
                })

        holdings.sort(key=lambda x: x['value'], reverse=True)

        report = {
            'date': self.current_date,
            'portfolio_value': portfolio_value,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'cash': self.cash,
            'num_positions': len([h for h in holdings]),
            'trades_today': len([t for t in self.trades if t['date'] == self.current_date]),
            'sharpe_ratio': sharpe,
            'holdings': holdings[:5]  # Top 5
        }

        return report

    def save_daily_report(self, prices):
        """Save daily report to file"""
        report = self.get_daily_report(prices)

        filename = os.path.join(
            DAILY_REPORT_DIR,
            f"report_{self.current_date.strftime('%Y%m%d')}.json"
        )

        with open(filename, 'w') as f:
            # Make report JSON serializable
            report_clean = {
                'date': report['date'].isoformat(),
                'portfolio_value': float(report['portfolio_value']),
                'total_pnl': float(report['total_pnl']),
                'total_pnl_pct': float(report['total_pnl_pct']),
                'cash': float(report['cash']),
                'num_positions': int(report['num_positions']),
                'trades_today': int(report['trades_today']),
                'sharpe_ratio': float(report['sharpe_ratio']),
                'holdings': [
                    {
                        'symbol': h['symbol'],
                        'shares': float(h['shares']),
                        'price': float(h['price']),
                        'value': float(h['value']),
                        'entry_price': float(h['entry_price']),
                        'pnl_pct': float(h['pnl_pct'])
                    }
                    for h in report['holdings']
                ]
            }
            json.dump(report_clean, f, indent=2)

        return report

    def run_day(self):
        """Run trading for one day"""
        prices = self.get_current_prices()

        if not all(prices.values()):
            log.warning("Could not fetch all prices, skipping")
            return

        # Execute step
        self.step(prices)

        # Record portfolio value
        portfolio_value = self.get_portfolio_value(prices)
        self.daily_values.append(portfolio_value)

        # Save report
        report = self.save_daily_report(prices)

        # Log
        log.info(f"[{self.current_date}] Portfolio: ${portfolio_value:,.0f} "
                 f"(P&L: {report['total_pnl_pct']:+.2f}%) | "
                 f"Positions: {report['num_positions']} | "
                 f"Trades: {report['trades_today']}")

        return report

    def save_trades_log(self):
        """Save all trades to CSV"""
        df_trades = pd.DataFrame(self.trades)
        df_trades.to_csv(PAPER_TRADING_LOG, index=False)
        log.info(f"Saved {len(self.trades)} trades to {PAPER_TRADING_LOG}")

    def get_performance_summary(self):
        """Generate performance summary"""
        if not self.daily_values:
            return {}

        daily_values = np.array(self.daily_values)
        returns = np.diff(daily_values) / daily_values[:-1]

        total_return = (daily_values[-1] - self.initial_amount) / self.initial_amount
        annual_return = total_return * (252 / len(daily_values))

        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0

        running_max = np.maximum.accumulate(daily_values)
        drawdown = (daily_values - running_max) / running_max
        max_dd = np.min(drawdown)

        win_trades = len([t for t in self.trades if t.get('pnl', 0) > 0])
        total_trades = len([t for t in self.trades if t['action'] == 'SELL'])
        win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

        return {
            'total_return_pct': total_return * 100,
            'annual_return_pct': annual_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown_pct': max_dd * 100,
            'win_rate': win_rate,
            'total_trades': total_trades,
            'final_value': float(daily_values[-1])
        }

# ============================================================================
# MAIN LOOP
# ============================================================================

def run_paper_trading(days=30):
    """Run paper trading for N days"""
    log.info("="*70)
    log.info("  PAPER TRADING ENGINE")
    log.info("="*70)
    log.info(f"Initial Capital: ${INITIAL_AMOUNT:,}")
    log.info(f"Max Position:    ${MAX_POSITION:,}")
    log.info(f"Running for:     {days} days\n")

    engine = PaperTradingEngine(INITIAL_AMOUNT, MAX_POSITION)

    # Run for N days
    for i in range(days):
        engine.current_date = datetime.now() - timedelta(days=days-i)
        engine.run_day()

    # Save results
    engine.save_trades_log()

    # Summary
    summary = engine.get_performance_summary()

    log.info(f"\n{'='*70}")
    log.info(f"  PAPER TRADING SUMMARY ({days} days)")
    log.info(f"{'='*70}")
    log.info(f"  Final Value:         ${summary['final_value']:,.0f}")
    log.info(f"  Total Return:        {summary['total_return_pct']:+.2f}%")
    log.info(f"  Annualized Return:   {summary['annual_return_pct']:+.2f}%")
    log.info(f"  Sharpe Ratio:        {summary['sharpe_ratio']:.2f}")
    log.info(f"  Max Drawdown:        {summary['max_drawdown_pct']:.2f}%")
    log.info(f"  Win Rate:            {summary['win_rate']:.1f}%")
    log.info(f"  Total Trades:        {summary['total_trades']}")
    log.info(f"{'='*70}\n")

if __name__ == "__main__":
    run_paper_trading(days=30)
