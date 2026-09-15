#!/usr/bin/env python3
"""
Exit Monitor - Dry-Run Mode
Runs hourly to check bot trades from logs and suggest exits
Validates exit strategy before live deployment
"""

import re
import logging
import yfinance as yf
from datetime import datetime
from exit_strategy import MeanReversionExit

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler("dry_run_logs/exit_monitor.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

class ExitMonitor:
    """Monitor bot trades and suggest exits"""

    def __init__(self, log_file="dry_run_logs/bot_20260820.log"):
        self.log_file = log_file
        self.exit_mgr = MeanReversionExit()
        self.suggested_exits = []

    def parse_buy_trades(self):
        """Parse BUY trades from bot log"""
        try:
            with open(self.log_file, 'r') as f:
                lines = f.readlines()

            buys = []
            for line in lines:
                # Pattern: BUY | SYMBOL @ $PRICE | Llama XXX%
                if "| BUY |" in line:
                    match = re.search(r"BUY \| (\w+) @ \$([0-9.]+)", line)
                    if match:
                        symbol = match.group(1)
                        entry_price = float(match.group(2))

                        # Extract timestamp
                        time_match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
                        entry_time = time_match.group(1) if time_match else "unknown"

                        buys.append({
                            "symbol": symbol,
                            "entry_price": entry_price,
                            "entry_time": entry_time,
                            "raw_line": line.strip()
                        })

            log.info(f"Parsed {len(buys)} BUY trades from log")
            return buys

        except FileNotFoundError:
            log.error(f"Log file not found: {self.log_file}")
            return []

    def get_current_prices(self, symbols):
        """Get current prices for all symbols"""
        prices = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prices[symbol] = price
            except:
                prices[symbol] = 0

        return prices

    def check_exits(self):
        """Check all open positions for exit conditions"""
        # Parse trades from log
        buys = self.parse_buy_trades()

        if not buys:
            log.info("No BUY trades found in log")
            return []

        # Get current prices
        symbols = list(set([b["symbol"] for b in buys]))
        current_prices = self.get_current_prices(symbols)

        log.info(f"\n{'='*80}")
        log.info(f"EXIT MONITOR CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info(f"{'='*80}\n")

        log.info(f"Monitoring {len(buys)} open positions\n")

        exits = []

        for buy in buys:
            symbol = buy["symbol"]
            entry_price = buy["entry_price"]
            entry_time = buy["entry_time"]
            current_price = current_prices.get(symbol, 0)

            if current_price == 0:
                log.warning(f"Could not get price for {symbol}")
                continue

            # Calculate metrics
            pnl_percent = ((current_price - entry_price) / entry_price) * 100
            pnl_dollars = (current_price - entry_price) * (600 / entry_price)  # Assume $600 position

            # Parse entry time to check holding time
            try:
                entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
                holding_time = (datetime.now() - entry_dt).total_seconds() / 3600
            except:
                holding_time = 0

            # Check exit conditions
            log.info(f"{symbol}")
            log.info(f"  Entry: ${entry_price:.2f} | Current: ${current_price:.2f} | P&L: {pnl_percent:+.2f}% (${pnl_dollars:+.2f})")
            log.info(f"  Holding: {holding_time:.1f} hours")

            exit_reason = None
            exit_details = ""

            # 1. Profit target (+1.5%)
            if pnl_percent >= 1.5:
                exit_reason = "PROFIT_TARGET"
                exit_details = f"+{pnl_percent:.2f}% (target: +1.5%)"

            # 2. Stop loss (-1.5%)
            elif pnl_percent <= -1.5:
                exit_reason = "STOP_LOSS"
                exit_details = f"{pnl_percent:.2f}% (stop: -1.5%)"

            # 3. Time exit (4+ hours)
            elif holding_time >= 4:
                exit_reason = "TIME_EXIT"
                exit_details = f"Held {holding_time:.1f} hours (max: 4h)"

            # 4. Trailing stop (if profit, protect with 0.5% trail)
            elif pnl_percent > 0.5:
                peak_price = entry_price * 1.005  # 0.5% above entry
                if current_price < peak_price:
                    exit_reason = "TRAILING_STOP"
                    exit_details = f"Trail hit at {pnl_percent:.2f}%"

            if exit_reason:
                log.info(f"  ⚠️  EXIT SUGGESTED: {exit_reason}")
                log.info(f"      Reason: {exit_details}")
                log.info(f"      Action: SELL {symbol} @ ${current_price:.2f} | P&L: ${pnl_dollars:+.2f}\n")

                exits.append({
                    "symbol": symbol,
                    "entry_price": entry_price,
                    "current_price": current_price,
                    "pnl_percent": pnl_percent,
                    "pnl_dollars": pnl_dollars,
                    "holding_hours": holding_time,
                    "exit_reason": exit_reason,
                    "exit_details": exit_details,
                    "timestamp": datetime.now().isoformat()
                })
            else:
                log.info(f"  ✅ HOLD - No exit condition met\n")

        # Summary
        log.info(f"{'='*80}")
        log.info(f"SUMMARY")
        log.info(f"{'='*80}")
        log.info(f"Positions monitored: {len(buys)}")
        log.info(f"Exit suggestions: {len(exits)}")

        if exits:
            total_pnl = sum(e["pnl_dollars"] for e in exits)
            log.info(f"Total suggested P&L: ${total_pnl:+.2f}")
            log.info(f"\nExit summary:")
            for exit_info in exits:
                log.info(
                    f"  • {exit_info['symbol']}: "
                    f"${exit_info['pnl_dollars']:+.2f} ({exit_info['pnl_percent']:+.2f}%) "
                    f"via {exit_info['exit_reason']}"
                )

        log.info(f"{'='*80}\n")

        self.suggested_exits = exits
        return exits

    def save_suggestions(self):
        """Save exit suggestions to file"""
        if not self.suggested_exits:
            return

        import json
        with open("dry_run_logs/exit_suggestions.json", "a") as f:
            for exit_info in self.suggested_exits:
                f.write(json.dumps(exit_info) + "\n")

        log.info(f"Saved {len(self.suggested_exits)} exit suggestions")


if __name__ == "__main__":
    import sys

    # Determine log file based on today's date
    today = datetime.now().strftime("%Y%m%d")
    log_file = f"dry_run_logs/bot_{today}.log"

    monitor = ExitMonitor(log_file)
    exits = monitor.check_exits()
    monitor.save_suggestions()

    # Return exit count for scheduler
    sys.exit(len(exits))
