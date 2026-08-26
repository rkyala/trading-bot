#!/bin/bash
# Trading Bot Cycle Wrapper - Schwab + Robinhood MCP
# Called by cron: 0,30 9-14 * * 1-5 /Users/ramayalala/trading_bot/run_bot_cycle.sh

cd /Users/ramayalala/trading_bot

# Use Python 3.10 (Schwab API requirement)
PYTHON=/opt/homebrew/bin/python3.10

# Run bot (macOS doesn't have timeout, but bot runs in ~2 seconds)
$PYTHON bot_production_final.py >> bot_production.log 2>&1

exit 0
