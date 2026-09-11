#!/bin/bash
# ---------------------------------------------------------------------------
# Stop the UW bot at end of day.
#
# WHY THIS EXISTS
# uw_bot.py has TWO `while True` loops and NO exit path. It flattens positions
# at 15:45 local and then keeps running — overnight, through the weekend,
# indefinitely. start_uw_bot.sh has a duplicate guard that (correctly) refuses
# to start a second instance:
#
#     EXISTING=$(pgrep -f "unusual_whales_bot/uw_bot.py" | head -1 || true)
#     [ -n "$EXISTING" ] && exit 0
#
# So the next morning's 08:30 launchd start finds yesterday's process alive,
# prints "already running", and EXITS 0. The job looks like it succeeded. The
# bot never restarts, never re-reads config, never picks up any code change,
# and the day's session is silently the previous day's process.
#
# This is the same failure shape as the TCC problem: a scheduled job reporting
# success while doing nothing. It has been handled by remembering to kill the
# bot manually every evening, which is not a mechanism.
#
# TIMING
# 16:30 local. The bot's EOD force-close runs at 15:45 local (uw_bot.py uses
# datetime.now(), not an ET-aware clock), so 45 minutes of margin sits between
# the flatten and this kill. The market has been closed since 15:00 local.
#
# SIGTERM first so the process can close its log cleanly; SIGKILL only if it is
# still there 10 seconds later.
# ---------------------------------------------------------------------------
set -uo pipefail
cd /Users/ramayalala/trading_bot_uw || exit 1

LOG_FILE="logs/uw_bot_stop.log"
mkdir -p logs

PIDS=$(pgrep -f "unusual_whales_bot/uw_bot.py" || true)
if [ -z "$PIDS" ]; then
    echo "[$(date)] no UW bot running — nothing to stop" | tee -a "$LOG_FILE"
    exit 0
fi

echo "[$(date)] stopping UW bot (PID $PIDS)" | tee -a "$LOG_FILE"
# shellcheck disable=SC2086
kill -TERM $PIDS 2>/dev/null || true

for _ in $(seq 1 10); do
    sleep 1
    STILL=$(pgrep -f "unusual_whales_bot/uw_bot.py" || true)
    [ -z "$STILL" ] && break
done

STILL=$(pgrep -f "unusual_whales_bot/uw_bot.py" || true)
if [ -n "$STILL" ]; then
    echo "[$(date)] still alive after SIGTERM — SIGKILL $STILL" | tee -a "$LOG_FILE"
    # shellcheck disable=SC2086
    kill -9 $STILL 2>/dev/null || true
    sleep 1
fi

if pgrep -f "unusual_whales_bot/uw_bot.py" >/dev/null 2>&1; then
    echo "[$(date)] ❌ FAILED TO STOP — tomorrow's start will be skipped by the duplicate guard" | tee -a "$LOG_FILE"
    exit 1
fi

rm -f uw_bot.pid
echo "[$(date)] ✅ stopped — tomorrow's 08:30 start will run clean" | tee -a "$LOG_FILE"
exit 0
