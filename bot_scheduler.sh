#!/bin/bash
# Simple scheduler that runs bot every 30 minutes during market hours
# Run this in background: nohup bash bot_scheduler.sh > logs/scheduler.log 2>&1 &

BOT_DIR="/Users/ramayalala/trading_bot_uw"
LOG_DIR="$BOT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "Bot Scheduler Started - $(date)" >> "$LOG_DIR/scheduler.log"

while true; do
    HOUR=$(date -u +%H | sed 's/^0//')
    MIN=$(date -u +%M | sed 's/^0//')
    DOW=$(date +%w)
    DATE=$(date +%Y%m%d)

    # Market hours: 14-21 UTC (9:30-4:30 CDT), Mon-Fri (1-5)
    if [[ $HOUR -ge 14 && $HOUR -le 21 && $DOW -ge 1 && $DOW -le 5 ]]; then
        # Run at :00 and :30 of each hour
        if [[ $MIN == "0" || $MIN == "30" ]]; then
            echo "Running bot at $(date)" >> "$LOG_DIR/scheduler.log" 2>&1
            cd "$BOT_DIR"
            python3 bot_dry_run_v3.py >> "dry_run_logs/bot_${DATE}.log" 2>&1
            echo "Bot completed at $(date)" >> "$LOG_DIR/scheduler.log" 2>&1

            # Sleep 90 seconds to avoid running twice in same minute
            sleep 90
        fi
    fi

    # Check every 10 seconds
    sleep 10
done
