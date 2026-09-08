#!/bin/bash
##############################################################################
# Start UW Options Trading Bot
# Called by cron at 8:30 AM CDT every trading day (30 08 * * 1-5)
##############################################################################

set -e

cd "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/trading_bot"

mkdir -p logs
LOG_FILE="logs/uw_bot_$(date +%Y%m%d_%H%M%S).log"

# ---------------------------------------------------------------------------
# DUPLICATE GUARD
# Sep 8: this script had no guard, so the 8:30 cron would start a SECOND bot
# alongside any already-running instance. Two bots share open_positions.json
# and would both place entries — racing each other on the same account.
# ---------------------------------------------------------------------------
# Match on the script path only. The interpreter shows up as the full
# Python.app path on macOS, not the literal "python3" — an earlier pattern
# required "python3" and therefore matched nothing, starting a second bot.
EXISTING=$(pgrep -f "unusual_whales_bot/uw_bot.py" | head -1 || true)
if [ -n "$EXISTING" ]; then
    echo "[$(date)] UW Bot already running (PID $EXISTING) — not starting a second instance" | tee -a "$LOG_FILE"
    exit 0
fi

# ---------------------------------------------------------------------------
# CREDENTIALS
# Sourced from .env.local (gitignored) rather than hardcoded in this file.
# They were previously inline here in plaintext; the file is untracked and the
# keys never reached git history, but one `git add -A` would have committed them.
# ---------------------------------------------------------------------------
if [ ! -f .env.local ]; then
    echo "[$(date)] ERROR: .env.local missing — refusing to start without credentials" | tee -a "$LOG_FILE"
    exit 1
fi
set -a
. ./.env.local
set +a

for v in UW_API_KEY RH_CLIENT_ID RH_REFRESH_TOKEN; do
    if [ -z "${!v}" ]; then
        echo "[$(date)] ERROR: $v not set in .env.local — refusing to start" | tee -a "$LOG_FILE"
        exit 1
    fi
done

echo "[$(date)] Starting UW Options Bot" | tee -a "$LOG_FILE"
nohup python3 -u unusual_whales_bot/uw_bot.py >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > uw_bot.pid
echo "[$(date)] UW Bot started with PID $BOT_PID (log: $LOG_FILE)" | tee -a "$LOG_FILE"
