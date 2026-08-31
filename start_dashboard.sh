#!/bin/bash
# Start Day Trading Alerts Dashboard
# Runs on @reboot to ensure dashboard is always available

DASHBOARD_DIR="/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/day_trading_alerts_management"
PYTHON="/opt/homebrew/bin/python3.10"
LOG_FILE="/Users/ramayalala/trading_bot/dashboard.log"

# Kill any existing instances
pkill -f "python3.10 -m http.server 8000"
sleep 1

# Start dashboard server
cd "$DASHBOARD_DIR"
$PYTHON -m http.server 8000 >> $LOG_FILE 2>&1 &

# Log startup
echo "[$(date)] Dashboard started on port 8000" >> $LOG_FILE

exit 0
