#!/bin/bash
#
# Block Trade Detector - 15-Minute Interval Runner
# Runs detector for 13 minutes, exits gracefully to avoid Schwab rate limits
# Scheduled via cron: */15 9-15 * * 1-5
#

set -e

PYTHON=/opt/homebrew/bin/python3.10
SCRIPT_DIR="/Users/ramayalala/trading_bot"
DETECTOR="$SCRIPT_DIR/schwab_block_trades.py"
LOG_FILE="$SCRIPT_DIR/block_trades.log"
TIMEOUT_SECS=780  # 13 minutes (leaves 2 min buffer before next 15-min cycle)

cd "$SCRIPT_DIR" || exit 1

# Log start time
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting block trade detector (13-min session)" >> "$LOG_FILE"

# Run detector with timeout
timeout "$TIMEOUT_SECS" "$PYTHON" "$DETECTOR" 2>&1 | tee -a "$LOG_FILE" || {
    exit_code=$?
    if [ $exit_code -eq 124 ]; then
        # Timeout (exit code 124) is expected - graceful stop
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Block trade detector cycle complete (timeout after 13 min)" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Block trade detector exited with code $exit_code" >> "$LOG_FILE"
    fi
}

# Ensure process is killed
pkill -f schwab_block_trades.py 2>/dev/null || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Block trade detector stopped - resuming next 15-min cycle" >> "$LOG_FILE"
