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

# macOS-compatible timeout using sleep + kill
(
    sleep "$TIMEOUT_SECS"
    pkill -f schwab_block_trades.py 2>/dev/null || true
) &
TIMEOUT_PID=$!

# Run detector and capture output
"$PYTHON" "$DETECTOR" 2>&1 | tee -a "$LOG_FILE"
DETECTOR_PID=$!

# Wait for detector to finish or timeout to kill it
wait $TIMEOUT_PID 2>/dev/null || true

# Ensure process is killed
pkill -f schwab_block_trades.py 2>/dev/null || true

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Block trade detector stopped - resuming next 15-min cycle" >> "$LOG_FILE"
