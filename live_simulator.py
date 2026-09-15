#!/usr/bin/env python3
"""
Live Simulator - Simulate live trading environment
Tracks position P&L in real-time, applies exits, records outcomes
"""

import re
import json
import logging
import yfinance as yf
from datetime import datetime
from exit_strategy import MeanReversionExit

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler("dry_run_logs/live_simulator.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

class LiveSimulator:
    """Simulate live trading with position tracking and exit execution"""

    def __init__(self, log_file="dry_run_logs/bot_20260820.log"):
        self.log_file = log_file
        self.exit_mgr = MeanReversionExit()
        self.positions_history = []

    def run_simulation(self):
        """Run full simulation"""
        log.info("\n" + "="*80)
        log.info("LIVE TRADING SIMULATOR")
        log.info("="*80 + "\n")

        # Parse all BUY trades
        buys = self.parse_trades()
        log.info(f"Loaded {len(buys)} BUY signals\n")

        if not buys:
            log.info("No trades to simulate")
            return

        # Process each trade
        for buy in buys:
            self.process_trade(buy)

        # Print final summary
        self.print_summary()

    def parse_trades(self):
        """Parse BUY trades from bot log"""
        try:
            with open(self.log_file, 'r') as f:
                lines = f.readlines()

            buys = []
            for line in lines:
                if "| BUY |" in line:
                    match = re.search(r"BUY \| (\w+) @ \$([0-9.]+)", line)
                    if match:
                        symbol = match.group(1)
                        entry_price = float(match.group(2))
                        time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                        entry_time = time_match.group(1) if time_match else "unknown"

                        buys.append({
                            "symbol": symbol,
                            "entry_price": entry_price,
                            "entry_time": entry_time,
                            "position_size": 600
                        })

            return buys
        except FileNotFoundError:
            log.error(f"Log file not found: {self.log_file}")
            return []

    def process_trade(self, buy):
        """Process a single trade through exit conditions"""
        symbol = buy["symbol"]
        entry_price = buy["entry_price"]
        position_size = buy["position_size"]

        # Get current price
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        except:
            current_price = 0
            log.warning(f"Could not get current price for {symbol}")
            return

        if current_price == 0:
            return

        # Calculate P&L
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        pnl_dollars = (current_price - entry_price) * (position_size / entry_price)

        # Simulate holding time (in real scenario, would check actual time)
        # For simulation, we'll assume positions held from entry to now
        try:
            entry_dt = datetime.strptime(buy["entry_time"], "%Y-%m-%d %H:%M:%S")
            holding_time = (datetime.now() - entry_dt).total_seconds() / 3600
        except:
            holding_time = 0

        # Determine exit
        exit_reason = None
        exit_price = current_price

        if pnl_percent >= 1.5:
            exit_reason = "PROFIT_TARGET"
            exit_price = entry_price * 1.015
        elif pnl_percent <= -1.5:
            exit_reason = "STOP_LOSS"
            exit_price = entry_price * 0.985
        elif holding_time >= 4:
            exit_reason = "TIME_EXIT"
        elif pnl_percent > 0.5:
            peak_price = entry_price * 1.005
            if current_price < peak_price:
                exit_reason = "TRAILING_STOP"
                exit_price = current_price

        # Recalculate if exit triggered
        if exit_reason:
            pnl_percent = ((exit_price - entry_price) / entry_price) * 100
            pnl_dollars = (exit_price - entry_price) * (position_size / entry_price)

        # Log trade
        trade_record = {
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price if exit_reason else current_price,
            "holding_hours": holding_time,
            "pnl_percent": pnl_percent,
            "pnl_dollars": pnl_dollars,
            "exit_reason": exit_reason or "OPEN",
            "entry_time": buy["entry_time"],
            "exit_time": datetime.now().isoformat()
        }

        self.positions_history.append(trade_record)

        # Print trade
        status = "CLOSED" if exit_reason else "OPEN"
        log.info(
            f"{status} | {symbol} | "
            f"Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f} | "
            f"P&L: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%) | "
            f"Reason: {exit_reason or 'Holding'}"
        )

    def print_summary(self):
        """Print simulation summary"""
        if not self.positions_history:
            log.info("No trades to summarize")
            return

        log.info("\n" + "="*80)
        log.info("SIMULATION SUMMARY")
        log.info("="*80 + "\n")

        trades = self.positions_history
        closed = [t for t in trades if t["exit_reason"] != "OPEN"]
        open_trades = [t for t in trades if t["exit_reason"] == "OPEN"]
        winners = [t for t in closed if t["pnl_dollars"] > 0]
        losers = [t for t in closed if t["pnl_dollars"] < 0]

        total_pnl = sum(t["pnl_dollars"] for t in trades)
        closed_pnl = sum(t["pnl_dollars"] for t in closed)
        avg_win = sum(t["pnl_dollars"] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t["pnl_dollars"] for t in losers) / len(losers) if losers else 0
        win_rate = (len(winners) / len(closed) * 100) if closed else 0

        log.info(f"Total Trades: {len(trades)}")
        log.info(f"Closed: {len(closed)} | Open: {len(open_trades)}")
        log.info(f"Winners: {len(winners)} | Losers: {len(losers)}")
        log.info(f"Win Rate: {win_rate:.1f}%")
        log.info(f"\nP&L Summary:")
        log.info(f"  Total P&L: ${total_pnl:+.2f}")
        log.info(f"  Closed P&L: ${closed_pnl:+.2f}")
        log.info(f"  Avg Win: ${avg_win:+.2f}")
        log.info(f"  Avg Loss: ${avg_loss:+.2f}")
        log.info(f"  Profit Factor: {abs(avg_win / avg_loss) if avg_loss != 0 else 0:.2f}x")

        # Exit reason breakdown
        log.info(f"\nExit Reasons:")
        exit_reasons = {}
        for trade in closed:
            reason = trade["exit_reason"]
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        for reason, count in sorted(exit_reasons.items()):
            log.info(f"  {reason}: {count} trades")

        log.info(f"\n{'='*80}\n")

        # Save simulation results
        self.save_results(total_pnl, win_rate, len(closed))

    def save_results(self, total_pnl, win_rate, closed_trades):
        """Save simulation results"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "simulation_type": "live_environment",
            "total_trades": len(self.positions_history),
            "closed_trades": closed_trades,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "trades_detail": self.positions_history
        }

        with open("dry_run_logs/simulation_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)

        log.info(f"Saved simulation results to simulation_results.json")


if __name__ == "__main__":
    today = datetime.now().strftime("%Y%m%d")
    log_file = f"dry_run_logs/bot_{today}.log"

    simulator = LiveSimulator(log_file)
    simulator.run_simulation()
