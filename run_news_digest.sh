#!/bin/bash
##############################################################################
# News digest — fetch, score, log, post to Discord.
#
# Runs as its own launchd job, NOT inside the bot's 300s loop. Two reasons:
#   1. model latency must never sit between a signal and an order; this is the
#      sidecar pattern already used by sentiment_worker.py
#   2. a crash here must not take the trading loop down
##############################################################################

set -e

# INTERPRETER DEPENDS ON THE BACKEND.
#
# The bot's 3.9 interpreter cannot run FinBERT: transformers >=4.57 refuses
# torch.load below torch 2.6 (CVE-2025-32434) and FinBERT ships as a .bin, and
# torch 2.6+ is not available for 3.9. So FinBERT lives in its own 3.10 venv.
#
# That venv is deliberately SEPARATE from the trading interpreter. Installing
# torch alongside the bot risked pip resolving a build that wants numpy<2 and
# silently downgrading numpy under pandas — while the bot holds live positions.
# Same reason sentiment_worker.py is a sidecar.
BACKEND="${SENTIMENT_BACKEND:-lexicon}"
if [ "$BACKEND" = "finbert" ]; then
    PYTHON="/Users/ramayalala/trading_bot_uw/venv_sentiment/bin/python"
else
    PYTHON="/Library/Frameworks/Python.framework/Versions/3.9/bin/python3"
fi

cd "/Users/ramayalala/trading_bot_uw"

# ---------------------------------------------------------------------------
# MARKET-HOURS GUARD.
#
# The agent uses StartInterval (every 5 min) rather than 70 StartCalendarInterval
# entries, so it fires around the clock and this guard is what confines it to
# the session. Polling every 5 min lets an URGENT headline reach Discord within
# minutes; the consolidated digest still posts only every 30 min. See the
# cadence note in uw_news_digest.py.
#
# Weekday 1-5, 08:25-15:05 CDT (a few minutes of slack either side of the
# 08:30-15:00 session).
# ---------------------------------------------------------------------------
DOW=$(date +%u)     # 1=Mon .. 7=Sun
HHMM=$(date +%H%M)
if [ "$DOW" -gt 5 ]; then
    exit 0
fi
if [ "$HHMM" \< "0825" ] || [ "$HHMM" \> "1505" ]; then
    exit 0
fi

if [ ! -x "$PYTHON" ]; then
    echo "[$(date)] ERROR: interpreter not found at $PYTHON" >&2
    exit 1
fi

if [ ! -f .env.local ]; then
    echo "[$(date)] ERROR: .env.local missing — refusing to run without credentials" >&2
    exit 1
fi
set -a
. ./.env.local
set +a

if [ -z "$UW_API_KEY" ]; then
    echo "[$(date)] ERROR: UW_API_KEY not set" >&2
    exit 1
fi

# DISCORD_WEBHOOK_URL absent is not fatal: the digest still fetches, scores and
# LOGS. The log is the point — it is what makes a future backtest possible —
# so a missing webhook must not stop collection.
if [ -z "$DISCORD_WEBHOOK_URL" ]; then
    echo "[$(date)] WARN: DISCORD_WEBHOOK_URL not set — logging only, no post"
    exec "$PYTHON" -u unusual_whales_bot/uw_news_digest.py
fi

echo "[$(date)] news digest (backend=$BACKEND, python=$(basename "$(dirname "$(dirname "$PYTHON")")"))"
exec "$PYTHON" -u unusual_whales_bot/uw_news_digest.py --post
