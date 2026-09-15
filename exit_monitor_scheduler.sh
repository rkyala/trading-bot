#!/bin/bash
# Exit Monitor Scheduler
# Runs exit_monitor.py every hour during market hours (9:30 AM - 4:30 PM CDT)

BOT_DIR="/Users/ramayalala/trading_bot_uw"
LOG_DIR="$BOT_DIR/dry_run_logs"
MONITOR_SCRIPT="$BOT_DIR/exit_monitor.py"

mkdir -p "$LOG_DIR"

echo "$(date) | Exit Monitor Scheduler Started"

while true; do
    HOUR=$(date +%H | sed "s/^0//")
    MINUTE=$(date +%M | sed "s/^0//")

    # Market hours: 9:30 AM - 4:30 PM CDT
    if [ $HOUR -ge 9 ] && [ $HOUR -le 16 ]; then
        if [ $HOUR -eq 16 ] && [ $MINUTE -gt 30 ]; then
            echo "$(date) | Market closed, waiting"
            sleep 300
        else
            echo "$(date) | Running exit monitor..."
            python3 "$MONITOR_SCRIPT" >> "$LOG_DIR/exit_monitor.log" 2>&1
            echo "$(date) | Exit monitor complete, next check in 1 hour"
            sleep 3600
        fi
    else
        echo "$(date) | Market closed, waiting until 9:30 AM"
        sleep 300
    fi
done
