# Adaptive Trading System - Options 2 & 4 Deployed

## 📊 Architecture Upgrade

### Option 2: Daily FinRL Retraining ✅
**Status:** ENABLED

**What it does:**
- FinRL model retrains **every day** at 20:00 UTC (3:00 PM CDT)
- Uses last 60 days of data (instead of 365)
- Faster adaptation to market regime changes
- Auto-deploys if Sharpe >= 1.8 (prevents overfitting)
- Falls back to previous model if Sharpe < 1.8

**Why daily vs weekly:**
- Weekly (old): Only updates Wednesdays & Sundays → misses mid-week patterns
- Daily (new): Captures daily market regime shifts → faster learning

**Cost:** ~5 min training per day (local GPU, $0 API cost)

**File:** `daily_retrain.sh`

---

### Option 4: Online Learning (Adaptive Llama) ✅
**Status:** ENABLED

**What it does:**
- Tracks win rate by symbol for Llama's predictions
- **Dynamically adjusts confidence threshold** based on performance
- Lowers threshold if Llama is underperforming (-10% if <45% win rate)
- Raises threshold if Llama overconfident (+10-20% if poor win rate)
- Clamps adjustment between 50-75% (prevents extreme swings)

**Adaptive Logic:**
```
Win Rate >= 65%  → Confidence threshold -5%   (Llama good, trade more)
Win Rate >= 55%  → Confidence threshold  0%   (Llama okay, keep as is)
Win Rate >= 45%  → Confidence threshold +10%  (Llama poor, be selective)
Win Rate  < 45%  → Confidence threshold +20%  (Llama very poor, only high-confidence)
```

**Example:**
```
MSFT: Win rate 50% (1W/1L)
  → Adjustment: +0% 
  → Adaptive threshold: 60% (same as default)

INTC: Win rate 30% (1W/3L)
  → Adjustment: +20%
  → Adaptive threshold: 80% (requires much higher confidence)

NVDA: Win rate 75% (3W/1L)
  → Adjustment: -5%
  → Adaptive threshold: 55% (trade more often)
```

**File:** `online_learning.py`

---

## 🔄 Combined System Flow

```
Every 30 minutes (market hours):
  1. Bot runs analysis (bot_dry_run.py)
  2. Llama 3.2 3B generates trade signal (50-100% confidence)
  3. OnlineLearner gets adaptive threshold for symbol
  4. If Llama confidence >= adaptive_threshold → BUY signal
  5. FinRL metrics confirmed (Sharpe > 1.5)
  6. Trade logged to hypothetical log

Every day at 20:00 UTC (3:00 PM CDT):
  7. Daily FinRL retrain runs
  8. Trains on last 60 days
  9. Auto-deploys if Sharpe >= 1.8
```

---

## 📅 Updated Cron Schedule

```bash
# Bot every 30 min (9:30 AM - 4:30 PM CDT, Mon-Fri)
*/30 14-21 * * 1-5 /path/to/run_bot_cron.sh

# FinRL daily retrain at 20:00 UTC (3:00 PM CDT)
0 20 * * * /path/to/daily_retrain.sh

# Backup weekly retrain (Wed & Sun)
0 20 * * 0,3 /path/to/weekly_retrain.sh
```

---

## 📈 Expected Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **FinRL adaptation** | Weekly (Wed/Sun only) | **Daily** |
| **Llama threshold** | Fixed at 60% | **Adaptive per symbol** |
| **Market response** | 3-4 days lag | **Same day** |
| **Win rate tracking** | Manual | **Automatic** |
| **Overfitting protection** | Sharpe gate | **Sharpe gate + daily review** |

---

## 🚀 Next Steps

1. **Monitor dry-run for 3-5 days**
   - Track adaptive thresholds as they adjust
   - Verify FinRL daily retrains complete
   - Collect trade performance data

2. **Review trade performance**
   - Check if win rate improves with adaptive thresholds
   - Validate FinRL Sharpe stays >= 1.8
   - Look for faster signal adaptation

3. **Enable live MCP trading**
   - Once performance stabilizes
   - Deploy to Railway with real orders
   - Monitor position dedup + auth errors

---

## 📊 Metrics to Watch

- **Llama accuracy:** Win rate per symbol (tracked in `trade_performance.json`)
- **Adaptive thresholds:** Should vary by symbol based on performance
- **FinRL Sharpe:** Daily trained model should maintain > 1.8
- **Bot execution:** Every 30 min during market hours
- **Retrain timing:** Daily at 3:00 PM CDT (20:00 UTC)

---

## 🔧 Configuration Files

- `bot_dry_run.py` — Updated to use OnlineLearner + adaptive thresholds
- `online_learning.py` — NEW: Tracks performance, calculates adaptive thresholds
- `daily_retrain.sh` — NEW: Daily FinRL retraining script
- `run_bot_cron.sh` — Wrapper for cron execution
- `ADAPTIVE_LEARNING_SETUP.md` — This file

---

**Deployed:** 2026-08-18 10:33 CDT
**Version:** Options 2 + 4 (Daily FinRL + Online Learning)
