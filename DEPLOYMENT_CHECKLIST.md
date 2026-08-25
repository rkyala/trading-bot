# Parallel Signal Channel - Deployment Checklist

## ✅ Pre-Flight Validation (COMPLETE)

- [x] **Python environment**: Python 3.9.6 ready
- [x] **Required files**: test_async_signal_channel.py, macro_signal_integrator.py, config.json
- [x] **Execution test**: 11s runtime (within safety window)
- [x] **Scan completion**: "SCAN COMPLETE" logged
- [x] **Atomic writes**: No .tmp file leaks
- [x] **Cron syntax**: Valid

## ⏳ Pre-Deployment (MANUAL)

### 1. Get FRED API Key (Optional but Recommended)
```bash
# Visit: https://fred.stlouisfed.org/docs/api/api_key.html
# Free key takes <2 minutes
# Update config.json:
```
Edit `~/trading_bot/config.json`:
```json
"macro_signals": {
  "fred_api_key": "YOUR_API_KEY_HERE",
  "fed_rate_cache_minutes": 5,
  "13f_scan_cache_hours": 4
}
```

### 2. Verify Paths Are Absolute
```bash
# The script uses Path(__file__).parent.resolve() for cron safety
# This ensures logs/queues go to ~/trading_bot, not ~/ or /tmp
```

### 3. Create Log Directory (If Needed)
```bash
touch ~/trading_bot/signal_channel.log
chmod 644 ~/trading_bot/signal_channel.log
```

## 🚀 Deployment (ONE COMMAND)

### Option 1: Interactive Crontab Edit
```bash
crontab -e
# Add this line:
* * * * * /Users/ramayalala/trading_bot/venv/bin/python3 /Users/ramayalala/trading_bot/test_async_signal_channel.py >> /Users/ramayalala/trading_bot/signal_channel.log 2>&1
```

### Option 2: Non-Interactive Crontab Add (If Interactive Fails)
```bash
# Get current crontab
CRON=$(crontab -l 2>/dev/null || echo "")

# Check if already exists
if ! echo "$CRON" | grep -q "test_async_signal_channel"; then
    # Add new job
    echo "$CRON" > /tmp/cron_backup.txt
    (echo "$CRON"; echo "* * * * * /Users/ramayalala/trading_bot/venv/bin/python3 /Users/ramayalala/trading_bot/test_async_signal_channel.py >> /Users/ramayalala/trading_bot/signal_channel.log 2>&1") | crontab -
    echo "✅ Cron job added"
else
    echo "ℹ️  Cron job already exists"
fi
```

## 📊 Post-Deployment Verification

### 1. Verify Cron Is Running (After 60 Seconds)
```bash
# Check that new entries appear in log
tail -f ~/trading_bot/signal_channel.log

# Expected output every 60 seconds:
# 2026-08-24 13:38:00,123 | INFO | === PARALLEL SIGNAL CHANNEL SCAN ===
# 2026-08-24 13:38:02,456 | INFO | Scanning 13-F filings...
# 2026-08-24 13:38:05,789 | INFO | === SCAN COMPLETE ===
```

### 2. Verify Queue File Is Being Updated
```bash
# Check timestamp updates
stat ~/trading_bot/macro_triggers.json | grep Modify

# Run twice, 60 seconds apart:
ls -l ~/trading_bot/macro_triggers.json
# (repeat after 60 seconds)
# Timestamp should advance by ~60 seconds
```

### 3. Verify No Tmp File Leaks
```bash
# Should return nothing (no dangling tmp files)
ls -la ~/trading_bot/macro_triggers.tmp 2>&1 | grep -q "No such file" && echo "✅ Clean" || echo "❌ Tmp file leaked"
```

### 4. Monitor for Errors (First 5 Minutes)
```bash
# Check for any ERROR or exception messages
tail -50 ~/trading_bot/signal_channel.log | grep -i "error\|exception\|failed"

# Should see mostly INFO messages, no ERRORS
```

## 🛑 Rollback (If Issues)

### Remove from Crontab
```bash
crontab -e
# Delete the signal channel line, save and exit
```

### Verify Removed
```bash
crontab -l | grep test_async_signal_channel
# Should return nothing
```

### Keep Logs for Debug
```bash
cp ~/trading_bot/signal_channel.log ~/trading_bot/signal_channel.log.backup
```

## 📋 Critical Fixes Applied

1. **SEC EDGAR User-Agent**: Added mandatory header (prevents HTTP 403)
2. **FRED API Authentication**: Config-based API key + JSON format (prevents HTTP 400/401)
3. **Atomic File Writes**: Tmp file + atomic rename (prevents bot from reading partial files)
4. **Path Resolution**: `Path(__file__).parent.resolve()` (prevents cron writing to wrong location)
5. **Timeout Resilience**: 4-second timeout on EDGAR + graceful degradation

## 🔐 Safety Guarantees

✅ **Non-blocking**: If signal channel crashes, bot continues unaffected  
✅ **Atomic writes**: Bot never reads partially-written macro_triggers.json  
✅ **Graceful degradation**: Missing API keys skip that source, don't crash  
✅ **No tmp leaks**: Atomic rename ensures cleanup on all paths  
✅ **Absolute paths**: Cron writes to expected location, never home dir  

## 📈 Expected Behavior

**Steady State** (every 60 seconds):
```
✅ Macro data fetch: 1-2 seconds
✅ 13-F scan: 5-8 seconds (every 4 hours only; cached result other times)
✅ Options sweep: <1 second
✅ Queue update: <0.5 seconds
✅ Total: 6-11 seconds per cycle
```

**High Variance** (infrequent):
- First 13-F scan of 4-hour window: +5-8s (normal)
- EDGAR timeout (network issue): Retry next cycle (graceful)
- Missing FRED key: Fed rate skipped, other signals proceed (graceful)

## 🎯 Next Integration Steps

### Phase 2.5a: Verify Signal Queue
Run this monthly:
```bash
cat ~/trading_bot/macro_triggers.json | jq '.meta'
# Should show: total_signals, signal_types, last_update
```

### Phase 2.5b: Bot Integration (Optional)
In `bot_production_final.py`, during entry loop:
```python
from macro_signal_integrator import MacroSignalIntegrator
macro_signal = MacroSignalIntegrator.get_signal_for_symbol(symbol)
if macro_signal:
    confidence = MacroSignalIntegrator.boost_confidence(confidence, macro_signal, tech_bias)
```

---

**Ready to deploy?** Run:
```bash
crontab -e
# Add the * * * * * line above
```

Monitor: `tail -f ~/trading_bot/signal_channel.log`
