# 🔄 Log Rotation Setup Instructions

## Status: ✅ Configuration Ready

Log rotation configuration has been created at:
```
/Users/ramayalala/trading_bot/logrotate_trading_bot.conf
```

## Quick Setup (2 Steps)

### Step 1: Verify Logrotate Config
```bash
cat /Users/ramayalala/trading_bot/logrotate_trading_bot.conf
```

Expected output:
- Rotates daily
- Keeps 7-day history
- Compresses old logs
- Applies to bot_cycle.log, signal_channel.log, bot_production.log

### Step 2: Add to Crontab
Run this in your terminal:

```bash
crontab -e
```

Add this line at the **end** of your crontab:

```
0 2 * * * /usr/sbin/logrotate /Users/ramayalala/trading_bot/logrotate_trading_bot.conf >> /Users/ramayalala/trading_bot/logrotate.log 2>&1
```

Save and exit (Ctrl+X in nano, :wq in vim).

### Step 3: Verify Installation
```bash
crontab -l | grep logrotate
```

You should see the logrotate line.

## How It Works

**Daily at 2:00 AM UTC (9:00 PM CDT previous day):**

1. Renames current log files:
   - `bot_cycle.log` → `bot_cycle.log.1`
   - `bot_cycle.log.1` → `bot_cycle.log.2.gz`
   - etc.

2. Keeps only the last 7 days

3. Compresses logs older than 1 day (saves ~90% disk space)

4. Creates new empty log file for bot to write to

## Manual Rotation (Testing)

To manually rotate logs right now:

```bash
/usr/sbin/logrotate -f /Users/ramayalala/trading_bot/logrotate_trading_bot.conf
```

Check results:

```bash
ls -lah ~/trading_bot/*.log*
```

## Monitoring Logrotate

Check if cron job ran successfully:

```bash
tail ~/trading_bot/logrotate.log
```

Expected output:
```
rotating pattern: /Users/ramayalala/trading_bot/bot_cycle.log  weekly (7 rotations)
empty log files are not rotated, old logs are removed
```

## Disk Space Impact

**Before logrotate:**
- bot_cycle.log grows 1-2 MB per day
- After 30 days: ~30-60 MB

**After logrotate:**
- Only 7 days kept
- Compression reduces size by 90%
- Expected: ~1-2 MB total

---

## Production Hardening Summary

✅ **DONE:**
1. Atomic JSON Writes - Already implemented (tmp → rename)
2. Circuit Breaker Logic - Implemented (check_circuit_breaker method)
   - Halt trading if drawdown >= -40%
   - Hard position size cap: 0.5% max
3. Log Rotation - Configuration ready (just need to add 1 crontab line)

**Next: Add the logrotate line to crontab (Step 2 above)**
