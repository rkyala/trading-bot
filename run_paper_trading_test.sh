#!/bin/bash

##############################################################################
# Paper Trading 2-Day Validation Cycle
#
# Runs UW bot in paper trading mode for 2 days (Mon 9/8 + Tue 9/9)
# Logs all orders, decisions, and P&L
# Then generates review report
##############################################################################

set -e

SCRIPT_DIR="/Users/ramayalala/trading_bot_uw"
cd "$SCRIPT_DIR"

# Ensure paper trading is enabled
grep -q 'paper_trading": True' unusual_whales_bot/uw_config.py || {
    echo "❌ Paper trading not enabled in config"
    exit 1
}

echo ""
echo "╔════════════════════════════════════════════════════════════════════════╗"
echo "║                   PAPER TRADING VALIDATION CYCLE                       ║"
echo "║                      2 Days (Mon 9/8 - Tue 9/9)                        ║"
echo "╚════════════════════════════════════════════════════════════════════════╝"
echo ""

# Create log directory with timestamp
LOG_DIR="paper_trading_logs/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

echo "📍 Log directory: $LOG_DIR"
echo ""

# Export API keys
export UW_API_KEY="<UW_API_KEY_REDACTED — read it from .env.local, never inline>"
export RH_CLIENT_ID="<RH_CLIENT_ID_REDACTED — read it from .env.local, never inline>"
export RH_REFRESH_TOKEN="FZE10tFkDTWNhJIwzJKGedOMuVnGfr"
export DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"

# Check requirements
echo "Checking requirements..."
if [ -z "$RH_CLIENT_ID" ] || [ -z "$RH_REFRESH_TOKEN" ]; then
    echo "⚠️  WARNING: Robinhood tokens not set"
    echo "   Export before running:"
    echo "   export RH_CLIENT_ID=\"your_client_id\""
    echo "   export RH_REFRESH_TOKEN=\"your_token\""
    echo ""
fi

# Start bot
echo "🚀 Starting UW bot in PAPER TRADING mode..."
echo ""

python3 unusual_whales_bot/uw_bot.py 2>&1 | tee "$LOG_DIR/uw_bot.log" &

BOT_PID=$!
echo "   PID: $BOT_PID"
echo "   Mode: PAPER TRADING (no real money)"
echo ""
echo "📊 Log file: $LOG_DIR/uw_bot.log"
echo ""
echo "Watching for 2 days... (Press Ctrl+C to stop)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Monitor the bot
wait $BOT_PID

# Generate review report
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 GENERATING REVIEW REPORT..."
echo ""

python3 << 'REVIEW_SCRIPT'
import json
import re
from pathlib import Path
from datetime import datetime

log_file = Path("paper_trading_logs") / sorted(Path("paper_trading_logs").iterdir())[-1] / "uw_bot.log"

if not log_file.exists():
    print(f"❌ Log file not found: {log_file}")
    exit(1)

print(f"📖 Analyzing: {log_file}")
print("")

# Parse log
orders_placed = []
orders_rejected = []
errors = []
alerts_received = 0

with open(log_file) as f:
    for line in f:
        if "placed order" in line.lower() or "buy" in line.lower() or "sell" in line.lower():
            orders_placed.append(line.strip())
        elif "rejected" in line.lower() or "failed" in line.lower():
            orders_rejected.append(line.strip())
        elif "error" in line.lower() or "exception" in line.lower():
            errors.append(line.strip())
        if "alert" in line.lower() or "signal" in line.lower():
            alerts_received += 1

# Summary report
print("╔════════════════════════════════════════════════════════════════════════╗")
print("║                      PAPER TRADING REVIEW REPORT                       ║")
print("╚════════════════════════════════════════════════════════════════════════╝")
print("")
print(f"📊 STATISTICS:")
print(f"   Alerts processed: {alerts_received}")
print(f"   Orders placed: {len(orders_placed)}")
print(f"   Orders rejected: {len(orders_rejected)}")
print(f"   Errors: {len(errors)}")
print("")

if orders_placed:
    print(f"✅ ORDERS PLACED ({len(orders_placed)}):")
    for order in orders_placed[:10]:  # Show first 10
        print(f"   {order}")
    if len(orders_placed) > 10:
        print(f"   ... and {len(orders_placed) - 10} more")
    print("")

if errors:
    print(f"❌ ERRORS ({len(errors)}):")
    for error in errors[:5]:  # Show first 5
        print(f"   {error}")
    if len(errors) > 5:
        print(f"   ... and {len(errors) - 5} more")
    print("")

print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print("")
print("📋 REVIEW CHECKLIST:")
print("")
print("   [ ] No critical errors")
print("   [ ] Orders executing correctly")
print("   [ ] Phase 1 filter working")
print("   [ ] Phase 3B confidence scoring appropriate")
print("   [ ] Robinhood MCP communicating")
print("   [ ] Position tracking accurate")
print("   [ ] Risk management active (stops, exits)")
print("")
print("Once reviewed and validated:")
print("   1. Update config: paper_trading = False")
print("   2. Switch to REAL TRADING")
print("   3. Launch on Tuesday 9/8 at 8:30 AM CDT")
print("")

REVIEW_SCRIPT

echo "✅ Review complete"
echo ""
echo "Next steps:"
echo "  1. Review $LOG_DIR/uw_bot.log"
echo "  2. Check for errors or unusual behavior"
echo "  3. If satisfied: Update config to paper_trading=False"
echo "  4. Then launch real trading Tuesday"
echo ""
