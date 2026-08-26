#!/bin/bash
# Trading Bot Cycle Wrapper - Schwab + Robinhood MCP
# Called by cron: 0,30 9-14 * * 1-5 /Users/ramayalala/trading_bot/run_bot_cycle.sh

cd /Users/ramayalala/trading_bot

# Use Python 3.10 (Schwab API requirement)
PYTHON=/opt/homebrew/bin/python3.10

# Run bot with timeout protection (300 seconds = 5 min max)
timeout 300 $PYTHON bot_production_final.py >> bot_production.log 2>&1 || {
  EXIT_CODE=$?
  if [ $EXIT_CODE -eq 124 ]; then
    echo "Bot exceeded 300s timeout at $(date)" >> bot_production.log 2>&1
  fi
}

exit 0
