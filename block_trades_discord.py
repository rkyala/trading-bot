#!/usr/bin/env python3
"""
Block Trades Discord Alert Sender
Reads block_trades.csv and sends high-conviction trades to Discord
Monitors for new detections and posts real-time alerts
"""

import csv
import time
import sys
from pathlib import Path
from datetime import datetime
import requests
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Discord webhook
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1543798306650722374/hXV_yVr3S7VdHzMOGCkFoNhYxeukGQzTY7kW70lVpDC6Ei0my9OJ6elV6n4A37fclnXa"

# Block trades CSV file
BLOCK_CSV = Path("block_trades.csv")
SEEN_FILE = Path("block_trades_discord_sent.txt")

def load_sent_trades():
    """Load set of trades already sent to Discord"""
    if SEEN_FILE.exists():
        with open(SEEN_FILE, 'r') as f:
            return set(line.strip() for line in f)
    return set()

def save_sent_trade(trade_id):
    """Mark trade as sent"""
    with open(SEEN_FILE, 'a') as f:
        f.write(f"{trade_id}\n")

def send_discord_alert(trade_data):
    """Send block trade to Discord"""
    try:
        symbol = trade_data.get('symbol', '?')
        shares = trade_data.get('shares', 0)
        notional = trade_data.get('notional_value', 0)
        price = trade_data.get('price', 0)
        time_str = trade_data.get('time', '')
        tier = trade_data.get('tier', 'UNKNOWN')

        # Determine if large (>$1M)
        is_large = float(notional) > 1000000
        emoji = "🔥" if is_large else "📊"
        color = 16711680 if is_large else 3447003  # Red for mega, Blue for normal

        embed = {
            "title": f"{emoji} Block Trade - {symbol}",
            "color": color,
            "fields": [
                {"name": "Symbol", "value": symbol, "inline": True},
                {"name": "Shares", "value": f"{shares:,.0f}", "inline": True},
                {"name": "Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Notional", "value": f"${notional:,.0f}", "inline": True},
                {"name": "Time", "value": time_str, "inline": True},
                {"name": "Tier", "value": tier, "inline": True},
            ]
        }

        payload = {
            "username": "Block Trade Detector",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/3050/3050159.png",
            "embeds": [embed]
        }

        response = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)

        if response.status_code == 204:
            log.info(f"✅ Block trade alert sent: {symbol} {shares:.0f} shares @ ${price:.2f}")
            return True
        else:
            log.error(f"❌ Discord error: {response.status_code}")
            return False

    except Exception as e:
        log.error(f"❌ Failed to send alert: {e}")
        return False

def monitor_block_trades():
    """Monitor block_trades.csv for new detections"""
    sent_trades = load_sent_trades()

    log.info("🔍 Monitoring block trades...")

    if not BLOCK_CSV.exists():
        log.warning(f"⚠️  {BLOCK_CSV} not found yet. Waiting...")
        return

    # Read all trades
    try:
        with open(BLOCK_CSV, 'r') as f:
            reader = csv.DictReader(f)
            if not reader:
                return

            trades = list(reader)
    except Exception as e:
        log.error(f"Error reading CSV: {e}")
        return

    # Process new trades
    for trade in trades:
        trade_id = f"{trade.get('symbol', '?')}_{trade.get('time', '?')}_{trade.get('shares', '?')}"

        if trade_id not in sent_trades:
            # Send to Discord
            if send_discord_alert(trade):
                save_sent_trade(trade_id)
                sent_trades.add(trade_id)
            time.sleep(0.5)  # Rate limit

if __name__ == "__main__":
    monitor_block_trades()
    log.info("✅ Block trade monitoring complete")
