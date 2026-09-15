#!/bin/bash

# Bot Scheduler v3.5
# Runs bot_dry_run_v3_5.py every 30 minutes during market hours (9:30-16:30 CDT)

BOT_DIR="/Users/ramayalala/trading_bot_uw"
BOT_SCRIPT="$BOT_DIR/bot_dry_run_v3_5.py"
LOG_DIR="$BOT_DIR/dry_run_logs"

mkdir -p "$LOG_DIR"

while true; do
    HOUR=$(date +%H | sed 's/^0//')
    MINUTE=$(date +%M | sed 's/^0//')

    # Market hours: 9:30-16:30 CDT
    if [ $HOUR -ge 9 ] && [ $HOUR -le 16 ]; then
        if [ $HOUR -eq 16 ] && [ $MINUTE -gt 30 ]; then
            echo "$(date) | Market closed, waiting for tomorrow"
            sleep 300
        else
            echo "$(date) | Running cycle..."
            python3 "$BOT_SCRIPT" >> "$LOG_DIR/bot_$(date +%Y%m%d).log" 2>&1
            echo "$(date) | Cycle complete. Next cycle in 30 mins"
            sleep 1800
        fi
    else
        echo "$(date) | Market closed, waiting until 9:30"
        sleep 300
    fi
done
