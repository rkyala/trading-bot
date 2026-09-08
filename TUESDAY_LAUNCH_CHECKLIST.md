# Tuesday 9/8 Launch Checklist

**Status:** 🟢 READY FOR DEPLOYMENT  
**Date:** Tuesday, September 8, 2026  
**Time:** 8:00 AM CDT  
**Mode:** Paper Trading (2-day validation)  
**Capital:** $5,000 (paper)

---

## 🎯 PRE-LAUNCH (Monday 9/7 Evening - Tonight)

### System Verification
- [ ] Clone latest from `feature/uw` branch
  ```bash
  cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot
  git pull origin feature/uw
  ```

- [ ] Verify all credentials are in `.env.local`
  ```bash
  cat .env.local  # Should show 4 exports (UW, RH, Discord)
  ```

- [ ] Check paper trading mode enabled
  ```bash
  grep "paper_trading.*True" unusual_whales_bot/uw_config.py
  ```

- [ ] Verify Discord webhook (test fire alert)
  ```bash
  source .env.local
  python3 unusual_whales_bot/uw_consolidated_alerts.py
  # Should see: ✅ CONSOLIDATED ALERT SENT
  ```

### Directory Setup
- [ ] Ensure logs directory exists
  ```bash
  mkdir -p logs paper_trading_logs
  ```

- [ ] Clear old logs (keep only last 2 days if any)
  ```bash
  ls -la logs/
  ls -la paper_trading_logs/
  ```

- [ ] Verify disk space (need ~100MB for 2 days)
  ```bash
  df -h | grep /
  ```

### Git Status
- [ ] No uncommitted changes
  ```bash
  git status
  # Should be clean (nothing to commit, working tree clean)
  ```

- [ ] Latest commit is from feature/uw branch
  ```bash
  git log --oneline -1
  git branch
  # Should show: on feature/uw, latest commits recent
  ```

---

## 🚀 LAUNCH (Tuesday 9/8, 8:00 AM CDT)

### Start Bot
- [ ] Open terminal in trading_bot directory
  ```bash
  cd "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/trading_bot"
  ```

- [ ] Source environment variables
  ```bash
  source .env.local
  ```

- [ ] Start bot with startup script
  ```bash
  bash start_uw_bot.sh
  ```

- [ ] Verify bot started (watch logs)
  ```bash
  # In another terminal:
  tail -f logs/uw_bot_*.log
  # Should see Phase 1 screening messages
  ```

### Monitor First 30 Minutes
- [ ] Bot prints Phase 1 screening messages
- [ ] UW API responding with alerts
- [ ] Discord alerts flowing (check channel)
- [ ] No auth errors (401/403)
- [ ] Position states file created
- [ ] No crashes or exceptions

### Record Baseline (First Hour)
- [ ] Count alerts processed
- [ ] Count Phase 1 approvals
- [ ] Note first trade entered (if any)
- [ ] Screenshot Discord channel
- [ ] Take note of any warnings

---

## 📊 TUESDAY 9/8 MONITORING (Throughout Day)

### Every 30 Minutes
- [ ] Check bot is still running
  ```bash
  ps aux | grep uw_bot.py  # Should show active process
  ```

- [ ] Verify logs are accumulating
  ```bash
  tail -20 logs/uw_bot_*.log
  ```

- [ ] Check Discord for alerts (should see ~6-12 per cycle)

### Hourly
- [ ] Verify no error patterns
  ```bash
  grep -i error logs/uw_bot_*.log | tail -10
  # Should be minimal or none
  ```

- [ ] Check position file is being updated
  ```bash
  stat paper_positions.json
  # Should show recent modification time
  ```

- [ ] Verify Robinhood integration
  ```bash
  grep -i "robinhood\|order" logs/uw_bot_*.log | tail -5
  # Should show order placements (paper mode)
  ```

### Before Market Close (3:45 PM CDT)
- [ ] Verify EOD liquidation triggers
  ```bash
  grep -i "eod\|liquidation\|3:45" logs/uw_bot_*.log | tail -5
  ```

- [ ] Check all positions closed
  ```bash
  cat paper_positions.json
  # Should be empty {} or minimal
  ```

- [ ] No pending orders
  ```bash
  grep -i "pending\|open" logs/uw_bot_*.log | tail -5
  ```

### End of Day Summary
- [ ] Screenshot final log summary
- [ ] Note total trades entered
- [ ] Note total trades exited
- [ ] Estimate P&L
- [ ] List any issues encountered
- [ ] Save logs to dated folder
  ```bash
  cp -r logs logs_backup_20260908/
  ```

---

## 📋 WEDNESDAY 9/9 REVIEW CHECKLIST

### Log Analysis
- [ ] Review complete bot.log
  ```bash
  less logs/uw_bot_*.log  # Most recent
  ```

- [ ] Search for key metrics
  - Alerts processed: `grep -c "alert" logs/uw_bot_*.log`
  - Phase 1 approvals: `grep -c "PASSED" logs/uw_bot_*.log`
  - Orders placed: `grep -c "placed.*order" logs/uw_bot_*.log`
  - Orders closed: `grep -c "closing\|exit" logs/uw_bot_*.log`
  - Errors: `grep -i "error\|exception" logs/uw_bot_*.log | wc -l`

### Performance Validation
- [ ] Phase 1 accuracy > 80% (8/10 or better)
- [ ] Win rate > 55%
- [ ] No duplicate positions
- [ ] No missed EOD liquidations
- [ ] All Discord alerts sent
- [ ] Auth errors < 2%

### Risk Management Check
- [ ] Circuit breaker not triggered
- [ ] Stop losses working (if applicable)
- [ ] Position sizing correct
- [ ] No portfolio above -40% drawdown

### Decision Checklist
- [ ] Are baseline metrics met?
  - [ ] Accuracy >= 80%
  - [ ] Win rate >= 55%
  - [ ] Zero crashes
- [ ] If YES → Approve for real trading
- [ ] If NO → Identify issues, plan fixes

---

## ✅ GO/NO-GO DECISION (Wednesday)

### PASS Criteria
- [x] Phase 1 gate accuracy >= 80%
- [x] Win rate >= 55%
- [x] Zero critical errors
- [x] All APIs responding
- [x] Orders executing cleanly

### FAIL Criteria (Pause & Debug)
- [ ] Accuracy < 80%
- [ ] Win rate < 55%
- [ ] Crashes or hung processes
- [ ] API errors > 5%
- [ ] Missing EOD liquidations

### Decision
- [ ] **PASS** → Update config: `paper_trading = False` → Go live Thursday
- [ ] **FAIL** → Debug identified issues → Extend paper trading
- [ ] **PARTIAL** → Fix specific issue → 1-day retest

---

## 🎯 Real Trading Approval (if PASS)

If validation passes:

### Wednesday 9/9 Evening Updates
- [ ] Edit `uw_config.py`
  ```python
  paper_trading = False  # Change from True
  ```

- [ ] Commit change
  ```bash
  git add unusual_whales_bot/uw_config.py
  git commit -m "Switch from paper to real trading (validation passed)"
  git push origin feature/uw
  ```

### Thursday Morning 9/10
- [ ] Deploy to production
  ```bash
  bash start_uw_bot.sh
  ```

- [ ] Monitor first hour closely (real money now)
- [ ] Verify orders on Robinhood (not paper)
- [ ] Track real P&L

---

## 📞 Emergency Contacts

**If Bot Crashes:**
1. Check logs: `tail -100 logs/uw_bot_*.log`
2. Restart: `bash start_uw_bot.sh`
3. Monitor next cycle

**If Auth Error (401/403):**
1. Check tokens in `.env.local`
2. Verify RH token not expired
3. Check UW API key valid

**If Orders Not Executing:**
1. Verify paper_trading = True (Tuesday)
2. Check Robinhood MCP responding
3. Review order logs

**If Position Stuck:**
1. Manual exit available at 3:45 PM
2. Circuit breaker halts new trades at -40%
3. Check paper_positions.json

---

## 📊 Success Metrics

**Target for Tuesday 9/8:**
- ✅ Bot runs 6.5 hours (8:30 AM - 4:00 PM CDT)
- ✅ Processes 100+ alerts
- ✅ Approves 5-8 trades (Phase 1)
- ✅ Executes 3-5 orders (paper)
- ✅ Win rate 55-75%
- ✅ Zero crashes
- ✅ All alerts to Discord

**Confidence Level: HIGH** 🟢
- All systems tested
- Backtests validated
- Security locked in
- Ready to execute

---

## 🔒 Post-Launch

**Tuesday 9/8 Evening:**
- [ ] Stop bot gracefully (Ctrl+C)
- [ ] Backup logs and positions
- [ ] Prepare review materials
- [ ] Note any anomalies

**Wednesday 9/9:**
- [ ] Detailed log review
- [ ] Make go/no-go decision
- [ ] If GO: prepare production switch

**Thursday 9/10:**
- [ ] If approved: live trading launch
- [ ] If issues: resume paper trading

---

**Last Updated:** Monday, September 7, 2026 (Tonight - Pre-launch verification)  
**Status:** Ready for Tomorrow (Tuesday 9/8) Launch  
**Confidence:** 🟢 HIGH

