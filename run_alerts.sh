#!/bin/bash
# Warm up Python + run alerts with minimal overhead
cd "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/day_trading_alerts"

# Execute directly (no subshell overhead)
exec /opt/homebrew/bin/python3.10 -u alerts_consolidated.py >> /Users/ramayalala/trading_bot/alerts_consolidated.log 2>&1
