# 🎯 One-Week Dry Run Plan (Aug 19-23, 2026)

## 📋 Overview

Running the **enhanced trading bot** as a week-long dry run to validate:
- ✅ System consistency across 45+ cycles
- ✅ Trade quality (win rate, profit per trade)
- ✅ Llama + RAG + Ensemble performance
- ✅ Real-world market conditions
- ✅ Daily execution reliability

**No real money at risk** — logging hypothetical trades only.

---

## 📅 Schedule

### Daily Cycle (Mon-Fri)
- **Start**: 9:30 AM CDT (14:30 UTC)
- **End**: 4:30 PM CDT (21:30 UTC)
- **Frequency**: Every 30 minutes
- **Cycles/Day**: ~9 executions

### Weekly Total
- **Trading Days**: 5
- **Total Cycles**: 45
- **Total Symbols**: 5 (INTC, AMD, NVDA, MSFT, TSLA)
- **Expected Trades**: 20-30 (assuming 45-65% entry rate)

---

## 🤖 Systems Running

### Core Analysis
1. **Llama 3.2 3B** (Local)
   - Technical indicator context (RSI, VWAP, Bollinger Bands)
   - Trend identification (uptrend, downtrend, range)
   - Confidence generation (0-100%)

2. **FinRL Model** (Sharpe 2.94)
   - Risk-adjusted returns
   - Market regime detection
   - Position sizing guidance

3. **Enhanced Prompting** ✨
   - Provides rich technical context to Llama
   - Expected confidence boost: +40-80%

4. **RAG System** ✨
   - Retrieves similar winning patterns
   - Validates setup similarity
   - Learns from trade outcomes

5. **Ensemble Voting** ✨
   - Combines Llama (60%) + FinRL (40%)
   - Reduces false signals
   - Improves consistency

6. **Online Learning**
   - Tracks win rate per symbol
   - Adjusts confidence thresholds dynamically
   - Adapts to market conditions

---

## 📊 Daily Monitoring

### Each Morning (9:30 AM)
- ✅ Check if bot started successfully
- ✅ Verify Llama is responsive

### Each Evening (After 4:30 PM)
Run analysis:
```bash
python3 weekly_backtest.py 2026-08-19 2026-08-23
```

### Key Metrics to Track

| Metric | Target | Success Threshold |
|--------|--------|------------------|
| **Daily Trades** | 4-6 | ≥3 |
| **Avg Confidence** | 65-75% | ≥60% |
| **Win Rate** | 60-70% | ≥55% |
| **Daily Profit** | +$10-20 | ≥+$5 |
| **Total Weekly** | +$50-100 | ≥+$25 |

---

## 🎯 Expected Performance

### Conservative Estimate
- **Trades/Day**: 3-4
- **Win Rate**: 55%
- **Avg Profit**: +$5/trade
- **Daily Total**: +$8.25/day
- **Weekly**: +$41.25

### Realistic Estimate
- **Trades/Day**: 4-5
- **Win Rate**: 60%
- **Avg Profit**: +$6/trade
- **Daily Total**: +$14.40/day
- **Weekly**: +$72

### Optimistic Estimate
- **Trades/Day**: 5-6
- **Win Rate**: 65%
- **Avg Profit**: +$7/trade
- **Daily Total**: +$22.75/day
- **Weekly**: +$114

---

## ✅ Success Criteria

**Go-live approval requires:**

1. ✅ Win rate ≥ 55% (minimum profitability)
2. ✅ Avg confidence ≥ 60% (signal quality)
3. ✅ No system errors (100% uptime)
4. ✅ Total weekly profit ≥ +$25 (consistency)
5. ✅ No unexpected drawdowns (risk management)

---

## 🚀 Next Steps After Week

### If Success (All criteria met):
- **Week 2**: Deploy to LIVE TRADING
- Start with $600 position size
- Monitor real Robinhood orders
- Scale to $1000 after 5 profitable days

### If Needs Adjustment (1-2 criteria missed):
- Tune ensemble weights
- Adjust Llama confidence thresholds
- Add more symbols for diversity
- Run another week of validation

### If Unsuccessful (≥3 criteria missed):
- Analyze root cause
- Revise strategy or hyperparameters
- Extend dry run to 2 weeks
- Consider alternative approach

---

## 📁 Log Files & Reports

### Daily Logs
```
dry_run_logs/bot_20260819.log  (Monday)
dry_run_logs/bot_20260820.log  (Tuesday)
dry_run_logs/bot_20260821.log  (Wednesday)
dry_run_logs/bot_20260822.log  (Thursday)
dry_run_logs/bot_20260823.log  (Friday)
```

### Performance Summaries
```
dry_run_logs/performance_20260819.json
dry_run_logs/performance_20260820.json
... (etc)
```

### Final Weekly Report
```
weekly_backtest_report.json
```

---

## 🔔 Monitoring Commands

### Check Bot Status
```bash
ps aux | grep bot_scheduler
```

### View Today's Log
```bash
tail -100 dry_run_logs/bot_20260818.log
```

### Generate Weekly Report
```bash
python3 weekly_backtest.py 2026-08-19 2026-08-23
```

### Monitor in Real-Time
```bash
tail -f dry_run_logs/bot_20260819.log
```

---

## 📈 What Success Looks Like

✅ **Monday (Aug 19)**
- 8-9 cycles executed
- 3-4 trades triggered
- ~$10-15 hypothetical profit
- Llama confidence: 60-75%

✅ **Tuesday-Thursday (Aug 20-22)**
- Consistent daily execution
- Similar trade patterns
- Win rate stable 55-60%
- Confidence improving with RAG learning

✅ **Friday (Aug 23)**
- Final cycle data collected
- Week totaling +$50-70 profit
- 20-25 total trades
- System ready for live deployment

---

## ⚠️ Risk Checks

**Will NOT go live if:**
- System crashes or skips cycles
- Win rate drops below 50%
- Llama becomes unavailable
- Ensemble produces contradictory signals
- Technical analysis fails to calculate

**Mitigation:**
- Scheduler auto-restarts if fails
- FinRL fallback if Llama unavailable
- Manual cycle execution available
- Daily monitoring catches issues early

---

## 🎯 Timeline

| Date | Action | Expected Result |
|------|--------|-----------------|
| **Sun 8/18** | Setup complete, scheduler running | System validated ready |
| **Mon 8/19** | Day 1: Monitor execution | 3-4 trades, +$10-15 |
| **Tue 8/20** | Day 2: Check consistency | Similar pattern |
| **Wed 8/21** | Day 3: Mid-week analysis | Performance tracking |
| **Thu 8/22** | Day 4: Confidence stabilizing | RAG learning evident |
| **Fri 8/23** | Day 5: Week completion | Generate final report |
| **Mon 8/26** | Go-live decision | Deploy if ≥55% win rate |

---

## 📞 Support & Debugging

If issues arise:
1. Check scheduler: `ps aux | grep bot_scheduler`
2. Check Ollama: `curl http://localhost:11434/api/tags`
3. Verify logs: `ls -lh dry_run_logs/`
4. Manual run: `python3 bot_dry_run.py`

---

**Status**: 🟢 **READY FOR WEEK-LONG DRY RUN**

**Start Date**: Monday, August 19, 2026 @ 9:30 AM CDT
**End Date**: Friday, August 23, 2026 @ 4:30 PM CDT
**Duration**: 5 trading days, ~45 cycles
**Target**: Validate enhanced system for live deployment
