# DRY-RUN SETUP: Validate Bot Before Live Trading

**Goal:** Run trading analysis for 3-5 days, log all decisions, calculate returns WITHOUT placing orders

**Status:** Ready to deploy  
**Duration:** 3-5 days of validation  
**Risk:** Zero (no orders placed)  
**Output:** Performance logs + hypothetical returns

---

## 📋 Quick Start (5 minutes)

### Step 1: Test the Dry-Run Script

```bash
cd "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/trading_bot"

# Test one cycle
python3 bot_dry_run.py

# Expected output:
# ================================================================================
#   DRY-RUN CYCLE #1 - 2026-08-18 09:30:00
# ================================================================================
# 
# BUY  | INTC @ $101.50 | Llama 82% | Sentiment POSITIVE | FinRL Sharpe 2.94
#   → Hypothetical trade logged for INTC
# SKIP | AMD @ $128.00 | Llama 55% | Sentiment NEUTRAL | FinRL Sharpe 2.94
# 
# ================================================================================
# DRY-RUN PERFORMANCE SUMMARY
# ================================================================================
# Trades analyzed: 5
# Would execute: 2
# 
# Best case (+3%): $42.50 (7.08%)
# Realistic (+1.5%): $21.25 (3.54%)
# Conservative (stop): -$18.75 (-3.13%)
```

### Step 2: Set Up Cron Job (Every 30 Minutes)

```bash
# Open cron editor
crontab -e

# Add this line (every 30 min, 9:30 AM - 4:00 PM ET, Mon-Fri):
*/30 14-21 * * 1-5 cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot && python3 bot_dry_run.py

# Note: 14-21 = 9:30 AM - 4:30 PM ET (UTC hours)
# Adjust for your timezone:
#   Eastern: 14-21
#   Central: 15-22
#   Mountain: 16-23
#   Pacific: 17-24
```

### Step 3: View Results (After First Cycle)

```bash
# View dashboard
python3 dry_run_dashboard.py

# Expected output:
# ================================================================================
#   DRY-RUN PERFORMANCE: 2026-08-18
# ================================================================================
# 
# Trades Analyzed: 5
# Would Execute: 2
# 
# BEST CASE SCENARIO (+3% target):
#   Total Profit: $42.50
#   Avg ROI: 7.08%
#   Per Trade: $8.50
# 
# REALISTIC SCENARIO (+1.5% target):
#   Total Profit: $21.25
#   Avg ROI: 3.54%
#   Per Trade: $4.25
# 
# CONSERVATIVE SCENARIO (stop loss):
#   Total Profit: -$18.75
#   Avg ROI: -3.13%
#   Per Trade: -$3.75
```

---

## 📁 What Gets Logged

### Daily Files Created

```
dry_run_logs/
├── bot_20260818.log              # Raw bot output
├── analysis_20260818.jsonl       # Line-by-line analysis (JSON)
└── performance_20260818.json     # Summary with hypothetical returns
```

### What Each Log Contains

**bot_20260818.log** (Human-readable)
```
2026-08-18 09:30:00 | INFO     | ================================================================================
2026-08-18 09:30:00 | INFO     |   DRY-RUN CYCLE #1 - 2026-08-18 09:30:00
2026-08-18 09:30:00 | INFO     | ================================================================================
2026-08-18 09:30:15 | INFO     | BUY | INTC @ $101.50 | Llama 82% | Sentiment POSITIVE | FinRL Sharpe 2.94
2026-08-18 09:30:15 | INFO     |   → Hypothetical trade logged for INTC
2026-08-18 09:30:30 | INFO     | SKIP | AMD @ $128.00 | Llama 55% | Sentiment NEUTRAL | FinRL Sharpe 2.94
```

**analysis_20260818.jsonl** (Machine-readable, one JSON object per line)
```json
{"timestamp":"2026-08-18T14:30:00+00:00","cycle":1,"symbol":"INTC","current_price":101.50,"llama2":{"decision":"BUY","confidence":82,"reason":"INTC: +2.1% change, anomaly 75/100"},"finrl":{"sharpe":2.94,"annual_return":115.0},"sentiment":{"sentiment_type":"POSITIVE","confidence":85},"would_trade":true}
{"timestamp":"2026-08-18T14:30:15+00:00","cycle":1,"symbol":"AMD","current_price":128.00,"llama2":{"decision":"SKIP","confidence":55,"reason":"AMD: -1.2% change, anomaly 45/100"},"finrl":{"sharpe":2.94,"annual_return":115.0},"sentiment":{"sentiment_type":"NEUTRAL","confidence":0},"would_trade":false}
```

**performance_20260818.json** (Summary with returns)
```json
{
  "date": "2026-08-18",
  "total_analyzed": 5,
  "trades_that_would_execute": 2,
  "best_case_scenario": {
    "target": "+3%",
    "total_profit": 42.50,
    "total_roi": 7.08
  },
  "realistic_scenario": {
    "target": "+1.5%",
    "total_profit": 21.25,
    "total_roi": 3.54
  },
  "conservative_scenario": {
    "target": "stop_loss",
    "total_profit": -18.75,
    "total_roi": -3.13
  },
  "trades": [
    {
      "timestamp": "2026-08-18T14:30:00+00:00",
      "symbol": "INTC",
      "entry_price": 101.50,
      "position_size": 600,
      "quantity": 5,
      "confidence": 82,
      "hypothetical_exits": {
        "+1%": {"price": 102.51, "profit": 5.05, "roi": 0.84},
        "+2%": {"price": 103.53, "profit": 10.15, "roi": 1.69},
        "+3%": {"price": 104.55, "profit": 15.25, "roi": 2.54},
        "stop_loss": {"price": 100.02, "profit": -7.40, "roi": -1.23}
      }
    }
  ]
}
```

---

## 🔍 How to Analyze Results

### Day 1 (First Run)

```bash
# After first cycle
python3 dry_run_dashboard.py

# Check:
# - Did Llama 2 make reasonable decisions?
# - Are there trades it marked as "would execute"?
# - Are hypothetical profits positive?
```

### Day 2-3 (Pattern Validation)

```bash
# Check consistency
for day in 18 19 20; do
  echo "=== Aug $day ==="
  python3 -c "
import json
with open('dry_run_logs/performance_2026080${day}.json') as f:
    s = json.load(f)
    print(f'Trades: {s[\"total_analyzed\"]}')
    print(f'Best case: \${s[\"best_case_scenario\"][\"total_profit\"]:.2f}')
    print(f'Realistic: \${s[\"realistic_scenario\"][\"total_profit\"]:.2f}')
  "
done
```

### Day 4-5 (Decision Point)

After 5 days of data:
- ✅ If realistic ROI is consistently positive → Ready for live trading
- ⚠️ If mixed (some profitable, some not) → Adjust parameters, run 5 more days
- ❌ If mostly negative → Review strategy, don't go live yet

---

## 🎯 Success Criteria

**Ready for Live Trading When:**

```
□ Llama 2 makes consistent decisions
  (not all BUY, not all SKIP)

□ At least 40% of analyzed trades would execute
  (not over-filtering)

□ Realistic scenario shows positive returns
  (target: +1.5% avg per trade)

□ No systematic pattern of false signals
  (e.g., always wrong on earnings day)

□ FinRL Sharpe ratio remains > 1.5
  (model is stable)

□ News sentiment helps more than hurts
  (check +POSITIVE trades vs -NEGATIVE trades)
```

---

## 📊 Example: 5-Day Dry-Run Results

```
DAY 1 (Aug 18):
  Analyzed: 5 | Execute: 2 | Best: +7.08% | Realistic: +3.54% ✓

DAY 2 (Aug 19):
  Analyzed: 6 | Execute: 3 | Best: +8.25% | Realistic: +4.12% ✓

DAY 3 (Aug 20):
  Analyzed: 4 | Execute: 1 | Best: +2.45% | Realistic: +1.20% ✓ (weak day)

DAY 4 (Aug 21):
  Analyzed: 7 | Execute: 4 | Best: +9.75% | Realistic: +4.87% ✓

DAY 5 (Aug 22):
  Analyzed: 5 | Execute: 2 | Best: +5.50% | Realistic: +2.75% ✓

SUMMARY (5 days):
  Total analyzed: 27 trades
  Would execute: 12 trades
  Avg realistic return: +3.30% per trade
  → READY FOR LIVE TRADING ✅
```

---

## 🚀 After Validation: Switch to Live Trading

When you're confident, edit the bot:

```bash
# Current: dry_run_mode = True (no orders)
# Change to: dry_run_mode = False (places real orders)

# Step 1: Update bot_dry_run.py
sed -i 's/DRY_RUN_MODE = True/DRY_RUN_MODE = False/' bot_dry_run.py

# Step 2: Rename to live bot
cp bot_dry_run.py bot.py

# Step 3: Update cron to use live bot
crontab -e
# Change: python3 bot_dry_run.py
# To: python3 bot.py
```

---

## 📈 Key Metrics to Track

**Create a spreadsheet with these columns:**

```
Date | Analyzed | Execute | Best +3% | Realistic +1.5% | Conservative Stop | Avg Confidence | Main Sentiment
-----|----------|---------|----------|-----------------|-------------------|----------------|---------------
18   | 5        | 2       | $42.50   | $21.25          | -$18.75           | 72%            | 60% POSITIVE
19   | 6        | 3       | $49.50   | $24.75          | -$22.50           | 76%            | 66% POSITIVE
20   | 4        | 1       | $14.80   | $7.20           | -$9.00            | 65%            | 50% NEUTRAL
21   | 7        | 4       | $58.50   | $29.25          | -$26.25           | 78%            | 71% POSITIVE
22   | 5        | 2       | $33.00   | $16.50          | -$16.50           | 70%            | 60% POSITIVE
```

**Calculate:**
- Running average ROI
- Consistency (std dev)
- Trend (improving or declining?)

---

## ⚠️ Common Issues & Fixes

### Issue: No trades executing ("Would Execute: 0")
```
Likely causes:
1. Llama 2 not running (is Ollama up?)
2. Confidence thresholds too high
3. FinRL model not loaded

Fix:
- Check if Llama available: python3 -c "from local_llm_wrapper import LocalLLMWrapper; print(LocalLLMWrapper().is_available())"
- Reduce confidence threshold (currently 60%)
- Check FinRL: python3 -c "from finrl_integration import get_finrl_metrics; print(get_finrl_metrics())"
```

### Issue: Dashboard shows "No logs found"
```
Solution:
1. Make sure bot_dry_run.py ran: check dry_run_logs/bot_*.log
2. If no logs, run: python3 bot_dry_run.py
3. Then: python3 dry_run_dashboard.py
```

### Issue: Returns don't match expectations
```
Check:
1. Are entry prices realistic? (should match yfinance)
2. Are target percentages reasonable? (+1%, +2%, +3%)
3. Is position size correct? ($600 per trade)
4. Is FinRL model loaded and working?
```

---

## 📋 Checklist: Ready for Live?

- [ ] Dry-run running for 3-5 days
- [ ] Dashboard shows consistent results
- [ ] Realistic scenario ROI positive
- [ ] Llama 2 making varied decisions
- [ ] FinRL Sharpe > 1.5
- [ ] News sentiment helping (not hurting)
- [ ] No obvious bugs in logs
- [ ] Cron job running on schedule
- [ ] You've reviewed sample trades
- [ ] You're comfortable with strategy

---

## 🎯 Next Steps

1. **Today:** Set up cron job with `bot_dry_run.py`
2. **Days 1-5:** Run dry-run, review logs daily
3. **Day 5:** Run `dry_run_dashboard.py`, analyze results
4. **Day 6:** Decide: Go live or run more validation?
5. **If ready:** Update to live mode, start placing orders

---

**Remember:** This is your chance to validate without risk. Take 3-5 days, build confidence, then go live! 🚀

