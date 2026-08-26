#!/bin/bash
# Block Trade Detector Wrapper - Runs continuously during market hours
# Called by cron at 9:00 AM: 0 9 * * 1-5 /Users/ramayalala/trading_bot/run_block_trades.sh

cd /Users/ramayalala/trading_bot

# Stop any existing block trade monitor
pkill -f "schwab_block_trades.py" || true
sleep 1

# Start new block trade monitor in background
/opt/homebrew/bin/python3.10 schwab_block_trades.py >> block_trade_stream.log 2>&1 &

# Log start
echo "$(date '+%Y-%m-%d %H:%M:%S') | Block trade stream started (PID: $!)" >> cron.log

exit 0
