#!/bin/bash
##############################################################################
# Start UW Options Trading Bot
# Called by cron at 8:30 AM CDT every trading day (30 08 * * 1-5)
##############################################################################

set -e

# ---------------------------------------------------------------------------
# INTERPRETER — pinned by absolute path.
# cron runs with PATH=/usr/bin:/bin, where `python3` resolves to
# /Library/Developer/CommandLineTools/usr/bin/python3 — a DIFFERENT 3.9 build
# with none of the bot's dependencies (yfinance, pandas, numpy, requests,
# httpx all missing). The 8:30 cron would have crashed on import every morning
# and failed silently. Resolving `python3` from PATH is not safe here.
# ---------------------------------------------------------------------------
PYTHON="/Library/Frameworks/Python.framework/Versions/3.9/bin/python3"

cd "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/trading_bot"

if [ ! -x "$PYTHON" ]; then
    echo "[$(date)] ERROR: interpreter not found at $PYTHON — refusing to start" >&2
    exit 1
fi

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

if ! "$PYTHON" -c "import yfinance, pandas, numpy, requests, httpx" 2>/dev/null; then
    echo "[$(date)] ERROR: $PYTHON is missing required packages — refusing to start" | tee -a "$LOG_FILE"
    exit 1
fi

echo "[$(date)] Starting UW Options Bot" | tee -a "$LOG_FILE"
nohup "$PYTHON" -u unusual_whales_bot/uw_bot.py >> "$LOG_FILE" 2>&1 &
BOT_PID=$!
echo "$BOT_PID" > uw_bot.pid
echo "[$(date)] UW Bot started with PID $BOT_PID (log: $LOG_FILE)" | tee -a "$LOG_FILE"
