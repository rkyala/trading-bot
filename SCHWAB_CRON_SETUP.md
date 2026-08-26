# Schwab Signal Fetcher - Cron Setup Guide

**Architecture:** Decoupled data fetching from trading execution  
**Fetcher:** Every 10 minutes (calculates signals)  
**Bot:** Every 30 minutes (executes trades using cached signals)  
**Result:** No yfinance needed, pure Schwab-powered trading  

---

## Cron Configuration

### Step 1: Add Signal Fetcher (Every 10 Minutes)

Edit crontab:
```bash
crontab -e
```

Add this line:
```bash
*/10 9-14 * * 1-5 /opt/homebrew/bin/python3.10 /Users/ramayalala/trading_bot/schwab_signal_fetcher.py >> /Users/ramayalala/trading_bot/schwab_signal_fetcher.log 2>&1
```

**Explanation:**
- `*/10` = Every 10 minutes
- `9-14` = 9 AM to 2 PM CST (market hours: 10:30 AM - 3:30 PM EST)
- `* * 1-5` = Every weekday
- Script: Fetches from Schwab, saves to `schwab_signals.json`
- Output: Logged to `schwab_signal_fetcher.log`

### Step 2: Update Bot Cron (Every 30 Minutes)

Existing bot cron:
```bash
0,30 9-14 * * 1-5 /path/to/run_bot_cycle.sh >> /path/to/cron.log 2>&1
```

**Keep as-is** - Bot will now read from `schwab_signals.json` instead of calling yfinance

---

## Cron Schedule Timeline

```
09:00 AM  ← Bot cycle starts (no signals yet)
09:10 AM  ← Signal fetcher runs (loads first signals)
09:30 AM  ← Bot cycle #2 uses signals from 09:10
09:40 AM  ← Signal fetcher runs (updates signals)
10:00 AM  ← Bot cycle #3 uses latest signals
10:10 AM  ← Signal fetcher runs
10:30 AM  ← Bot cycle #4 (market opens now)
...
02:00 PM  ← Last cycle (market closes at 3:00 PM CST / 4:00 PM EST)
02:10 PM  ← Last signal fetch
02:30 PM  ← Last bot cycle
```

**Result:** Bot always has fresh signals (max 10 min stale)

---

## Verification

### Check Signal Fetcher Log
```bash
tail -f schwab_signal_fetcher.log
```

Expected output:
```
SCHWAB SIGNAL FETCHER
================================================================================
Scanning 7 symbols for entry signals...
[2/7] MSFT ✅ SIGNAL
[5/7] TSLA ✅ SIGNAL

✅ Fetch complete!
   Scanned: 7 symbols
   Signals: 2 entry opportunities
   File: schwab_signals.json
```

### Check Signals File
```bash
cat schwab_signals.json | head -20
```

Expected output:
```json
{
  "timestamp": "2026-08-25T22:39:22.069288",
  "fetched_at": "2026-08-25 22:39:22",
  "total_scanned": 7,
  "signals_found": 2,
  "signals": [
    {
      "symbol": "MSFT",
      "price": 489.51,
      "adx": 29.15,
      "stoch_k": 13.78,
      ...
    },
    {
      "symbol": "TSLA",
      "price": 350.78,
      "adx": 23.00,
      ...
    }
  ]
}
```

### Check Bot Uses Schwab Signals
```bash
tail -f bot_production.log | grep -E "schwab|SIGNAL|Entry"
```

Expected output:
```
Using cached Schwab signals from 2026-08-25 22:39:22
📊 [MSFT] Price: $489.51 | ADX: 29.15 | Stoch: 13.78
🎯 ENTRY SIGNAL: MSFT BUY 1 @ $489.51
📊 [TSLA] Price: $350.78 | ADX: 23.00 | Stoch: 14.58
🎯 ENTRY SIGNAL: TSLA BUY 1 @ $350.78
```

---

## File Structure

```
bot_production_final.py
├── MarketDataFetcher class
│   └── Modified to read from schwab_signals.json
│       (Instead of calling yfinance)
│

schwab_signal_fetcher.py
├── Runs every 10 minutes (via cron)
├── Fetches from Schwab API
├── Calculates technicals
├── Detects entry signals
└── Saves to schwab_signals.json


schwab_signals.json
├── Latest signals from Schwab
├── Updated every 10 minutes
└── Bot reads this file
```

---

## Configuration

### Update run_bot_cycle.sh

Make sure it uses Python 3.10 and adds Schwab signal fetcher:

```bash
#!/bin/bash
cd /Users/ramayalala/trading_bot

# Optionally fetch fresh signals (usually already done by cron)
# /opt/homebrew/bin/python3.10 schwab_signal_fetcher.py

# Run bot with Schwab data
/opt/homebrew/bin/python3.10 bot_production_final.py
```

### Check Existing Cron

```bash
crontab -l
```

Should show:
```
*/10 9-14 * * 1-5 /opt/homebrew/bin/python3.10 /Users/ramayalala/trading_bot/schwab_signal_fetcher.py >> /Users/ramayalala/trading_bot/schwab_signal_fetcher.log 2>&1

0,30 9-14 * * 1-5 /Users/ramayalala/trading_bot/run_bot_cycle.sh >> /Users/ramayalala/trading_bot/cron.log 2>&1
```

---

## Constraints & Limits

### Schwab API Limits
- **Rate limit:** 120 requests/minute (plenty for our 10 symbols every 10 min)
- **Order limit:** 100 orders per day
- **Position limit:** No explicit limit, but account size dependent

### Bot Constraints
- **Signal freshness:** Max 10 minutes old (updated by fetcher every 10 min)
- **Bot frequency:** Every 30 minutes (matches existing schedule)
- **Max symbols:** 50 (limited by dynamic symbol fetcher)
- **Order limit:** Respect Schwab's 100 orders/day

### Recommended Limits
- **Max signals per bot cycle:** 10 (out of 50 symbols)
- **Max concurrent positions:** 5-10
- **Position size:** Keep existing limits ($50-$150 per position)
- **Daily order quota:** Reserve for exits (60 buys, 40 sells)

---

## Testing

### Manual Test (Before Deploying Cron)

```bash
# Test signal fetcher
/opt/homebrew/bin/python3.10 schwab_signal_fetcher.py

# Verify signals file created
cat schwab_signals.json | jq '.signals | length'
# Output: 2 (or number of signals)

# Test bot with cached signals
/opt/homebrew/bin/python3.10 bot_production_final.py

# Should see: "Using cached Schwab signals from..."
```

### Dry Run (No Real Trading)

```bash
# Set env var to disable actual order placement
export DRY_RUN=true
/opt/homebrew/bin/python3.10 bot_production_final.py
```

---

## Monitoring

### Real-Time Dashboard

```bash
# Terminal 1: Watch signal fetcher
tail -f schwab_signal_fetcher.log

# Terminal 2: Watch bot
tail -f bot_production.log

# Terminal 3: Check signal file
watch -n 5 'cat schwab_signals.json | jq -r ".fetched_at, .signals_found"'
```

### Alert Setup (Optional)

Monitor for errors:
```bash
# Check for signal fetcher errors (run every 15 min)
grep -i "error\|exception" schwab_signal_fetcher.log | tail -5

# Check for bot errors
grep -i "error\|exception" bot_production.log | tail -5
```

---

## Fallback Plan

If Schwab fails for 20+ minutes:

1. Signal fetcher will log error
2. Bot will use last known signals from `schwab_signals.json`
3. If signals > 30 min old, bot should skip trading

**Add to bot code:**
```python
# Check signal freshness
from datetime import datetime, timedelta
import json

signals = json.loads(Path("schwab_signals.json").read_text())
last_fetch = datetime.fromisoformat(signals["timestamp"])
age = (datetime.now() - last_fetch).total_seconds() / 60  # minutes

if age > 30:
    logger.warning(f"⚠️  Signals are {age:.0f}min old - skipping trading")
    return
```

---

## Deployment Steps

### Step 1: Deploy Signal Fetcher Cron
```bash
crontab -e
# Add: */10 9-14 * * 1-5 /opt/homebrew/bin/python3.10 /Users/ramayalala/trading_bot/schwab_signal_fetcher.py >> /Users/ramayalala/trading_bot/schwab_signal_fetcher.log 2>&1
```

### Step 2: Update Bot to Use Cached Signals
See `SCHWAB_BOT_MODIFICATION.md`

### Step 3: Test Manually
```bash
/opt/homebrew/bin/python3.10 schwab_signal_fetcher.py
/opt/homebrew/bin/python3.10 bot_production_final.py
```

### Step 4: Enable Bot Cron
Bot cron already set up - now it will use Schwab signals automatically

### Step 5: Monitor
```bash
tail -f schwab_signal_fetcher.log
tail -f bot_production.log
```

---

## Advantages of This Architecture

✅ **Separation of concerns:** Data fetching ≠ Trading execution  
✅ **Frequent updates:** Signals refreshed every 10 minutes  
✅ **Fast bot cycles:** Bot just reads cached JSON (milliseconds)  
✅ **No yfinance:** Pure Schwab, no API conflicts  
✅ **Resilient:** If Schwab fails mid-day, bot still works with cached signals  
✅ **Observable:** Each component has its own log file  
✅ **Scalable:** Can fetch from multiple data sources into same signals file  

---

**Next:** See `SCHWAB_BOT_MODIFICATION.md` for bot code changes
