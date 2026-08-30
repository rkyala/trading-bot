#!/bin/bash

# Day Trading Alerts - Cron Job Wrapper
# Run this every 5 minutes during market hours: */5 9-15 * * 1-5

PROJECT_DIR="/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/day_trading_alerts"
LOG_FILE="$PROJECT_DIR/logs/cron.log"

# Change to project directory
cd "$PROJECT_DIR" || exit 1

# Activate virtual environment if needed
# source venv/bin/activate

# Run alerts system
/usr/bin/python3 alerts_system.py >> "$LOG_FILE" 2>&1

exit 0
