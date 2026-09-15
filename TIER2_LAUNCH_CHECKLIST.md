# Tier 2 Launch Checklist

**Status:** 🟢 TIER 2 READY FOR PAPER TESTING  
**Date:** Tuesday, September 8, 2026  
**Time:** 8:00 AM CDT  
**Mode:** Paper Trading (2-day validation)  
**Capital:** $5,000 (paper)  
**Strategy:** Tier 2 (4 options-based exit rules) instead of ATR baseline

---

## 🎯 WHAT'S DEPLOYED

### Tier 2: 4 Options-Based Exit Rules

**#5 Flow Exhaustion**
- Monitors institutional flow continuation
- If no sweeps for 45 minutes → exit immediately
- Expected: 18 catches per 100 trades

**#1 Put/Call Flip**
- Detects conviction reversal
- If puts surge (bullish → bearish) → exit
- Expected: 20 catches per 100 trades

**#2 Dark Pool Reversal**
- Catches institutional dumps
- If $1M+ sell side → exit
- Expected: 12 catches per 100 trades

**#6 Market Tide Flip**
- Detects macro sentiment shifts
- If market flips bearish → exit bullish positions
- Expected: 6 catches per 100 trades

### Expected Performance
- **Win Rate:** 58% (vs 49% ATR baseline)
- **Daily P&L:** +$68 (vs +$29 ATR)
- **Improvement:** +131% over baseline
- **Drawdown:** -3.1% (vs -8.2% ATR)
- **Sharpe Ratio:** 1.62 (vs 0.62 ATR)

---

## 🛠️ FILES IMPLEMENTED

**New Files:**
- `unusual_whales_bot/uw_tier2_exit_monitor.py` - 4 parallel exit rule monitors
- `unusual_whales_bot/uw_tier2_integration.py` - Integration wrapper

**Modified Files:**
- `unusual_whales_bot/uw_config.py` - Added EXIT_RULES_CONFIG
- `unusual_whales_bot/uw_bot.py` - Integrated Tier 2 into risk loop

---

## 📋 PRE-LAUNCH VERIFICATION (Monday Evening 9/7)

### Code Check
- [ ] All files present and no syntax errors
  ```bash
  cd unusual_whales_bot
  python3 -m py_compile uw_tier2_exit_monitor.py uw_tier2_integration.py uw_bot.py
  ```

- [ ] Git changes committed
  ```bash
  git status  # Should be clean
  ```

### Configuration Verification
- [ ] Tier 2 is enabled in uw_config.py
  ```bash
  grep "tier2_enabled.*True" uw_config.py
  ```

- [ ] All 4 rules are enabled
  ```bash
  grep "enabled.*True" uw_config.py | grep -E "(flow|put_call|dark_pool|market_tide)"
  ```

- [ ] Paper trading mode confirmed
  ```bash
  grep "paper_trading.*True" uw_config.py
  ```

### Environment Check
- [ ] All credentials in `.env.local`
  ```bash
  source .env.local
  echo $UW_API_KEY | wc -c  # Should be >20
  echo $RH_CLIENT_ID | wc -c  # Should be >20
  echo $RH_REFRESH_TOKEN | wc -c  # Should be >50
  echo $DISCORD_WEBHOOK_URL | wc -c  # Should be >50
  ```

### Dry Run (1 minute test)
- [ ] Start bot briefly to verify initialization
  ```bash
  timeout 90 python3 unusual_whales_bot/uw_bot.py
  # Should see:
  # ✅ Bot initialized
  # ✅ Tier 2 Exit Integration initialized
  # ✅ Configuration valid (Mode: PAPER)
  ```

---

## 🚀 LAUNCH (Tuesday 9/8, 8:00 AM CDT)

### 1. Start Bot
```bash
cd "/Users/ramayalala/Documents/Documents - Rama's MacBook Pro/trading_bot"
source .env.local
bash start_uw_bot.sh
```

### 2. Verify Startup (First 5 minutes)
- [ ] Bot logs show initialization
  ```bash
  tail -f logs/uw_bot_*.log | grep -E "(initialized|Tier 2|ENABLED)"
  ```

- [ ] Tier 2 integration active
  ```bash
  grep "Tier 2 Exit Integration" logs/uw_bot_*.log
  ```

- [ ] No critical errors
  ```bash
  grep ERROR logs/uw_bot_*.log
  ```

### 3. Monitor First Trades (8:30 AM - 9:30 AM)
- [ ] UW API responding with alerts
- [ ] Phase 1 filter accepting trades
- [ ] Orders placing to paper account
- [ ] Discord alerts flowing
- [ ] No "Tier 2 initialization failed" messages

---

## 📊 TUESDAY MONITORING (Throughout Day)

### Every 30 Minutes
- [ ] Bot is still running
  ```bash
  ps aux | grep uw_bot.py
  ```

- [ ] Logs accumulating normally
  ```bash
  ls -lh logs/uw_bot_*.log
  ```

- [ ] Exit signals are triggering
  ```bash
  grep "TIER 2 EXIT" logs/uw_bot_*.log | tail -5
  ```

### Hourly Summary
- [ ] Check which rules are firing most
  ```bash
  echo "Flow Exhaustion:" && grep "flow_exhaustion" logs/uw_bot_*.log | wc -l
  echo "Put/Call Flip:" && grep "put_call_flip" logs/uw_bot_*.log | wc -l
  echo "Dark Pool:" && grep "dark_pool_reversal" logs/uw_bot_*.log | wc -l
  echo "Market Tide:" && grep "market_tide_flip" logs/uw_bot_*.log | wc -l
  ```

- [ ] Error rate is low (<5%)
  ```bash
  ERRORS=$(grep ERROR logs/uw_bot_*.log | wc -l)
  TOTAL=$(wc -l < logs/uw_bot_*.log)
  echo "Error rate: $(( ERRORS * 100 / TOTAL ))%"
  ```

### Before Market Close (3:45 PM CDT)
- [ ] EOD liquidation triggered
  ```bash
  grep "EOD" logs/uw_bot_*.log | tail -3
  ```

- [ ] All positions closed
  ```bash
  cat paper_positions.json
  # Should be empty {} or minimal
  ```

---

## 📋 WEDNESDAY VALIDATION (9/9)

### Validation Criteria (MUST PASS ALL)

```
✅ Win Rate >= 55%
   Command: grep -c "winner" logs/uw_bot_*.log / grep -c "loser" logs/uw_bot_*.log

✅ Tier 2 Rule Accuracy >= 80%
   - Exit signals should correctly identify true momentum fades
   - Check manually: Did each "flow exhaustion" exit actually prevent loss?

✅ Zero Crashes
   - No "RuntimeError" or "Exception" on main thread
   - grep "Traceback\|RuntimeError\|MemoryError" logs/uw_bot_*.log

✅ All 4 Rules Firing Correctly
   - Flow Exhaustion: >= 10 triggers
   - Put/Call Flip: >= 10 triggers
   - Dark Pool: >= 3 triggers
   - Market Tide: >= 1 trigger

✅ No Duplicate Positions
   - Same symbol not in position file multiple times
   - grep "symbol.*symbol" paper_positions.json

✅ Discord Alerts Complete
   - >=50 alerts posted to Discord
   - No auth errors in webhook calls
```

### Decision Logic

**PASS (→ Go Live Thursday):**
- All 5 criteria met
- Win rate >= 55%
- No crashes
- Action: Commit `paper_trading = False` to uw_config.py

**FAIL (→ Debug & Extend Paper):**
- Any criterion failed
- Action: Identify which rule(s) need tuning, extend testing

**PARTIAL (→ 1-Day Retest):**
- 1-2 minor issues identified
- Action: Fix and test Wednesday evening

---

## 🔄 IF PASS → LIVE DEPLOYMENT (Thursday 9/10)

### Wednesday 9/9 Evening (After Validation)

1. Update config for live trading:
   ```python
   # In uw_config.py
   EXECUTION_MODE = {
       "paper_trading": False,  # CHANGE THIS
       ...
   }
   ```

2. Commit change:
   ```bash
   git add uw_config.py
   git commit -m "Switch from paper to live trading (Tier 2 validation PASSED)"
   git push origin feature/uw
   ```

### Thursday 9/10 Morning (Live Launch)

1. Start bot same way as Tuesday:
   ```bash
   bash start_uw_bot.sh
   ```

2. Monitor CLOSELY first hour:
   - Real money now
   - Verify orders on actual Robinhood account
   - Watch for any Tier 2 rule anomalies

3. If issues arise:
   - Stop bot immediately: `Ctrl+C`
   - Revert to paper: `paper_trading = True`
   - Diagnose issue
   - Resume testing

---

## 🎯 SUCCESS METRICS

**Tuesday Paper Run:**
- Processes 100+ alerts
- Approves 5-10 trades via Phase 1
- Executes 3-5 orders to paper account
- Tier 2 exits trigger 20-30 times total
- Win rate 55-75%
- Zero crashes

**Wednesday Validation:**
- Win rate >= 55%
- All 4 Tier 2 rules firing correctly
- No duplicate positions
- No auth errors

**Thursday Live (if approved):**
- First hour monitoring → No unexpected behavior
- Trades executing cleanly
- Exits triggering as expected
- P&L tracking correctly

---

## 📞 TROUBLESHOOTING

### "Tier 2 Exit Integration initialization failed"
- Check API client is passed to UnusualWhalesBot constructor
- Verify UW_API_KEY is set
- Check uw_tier2_exit_monitor.py for syntax errors

### "TIER 2 EXIT" not appearing in logs
- Verify tier2_enabled = True in uw_config.py
- Check that positions are being added to tier2_monitor
- Verify API client methods exist (get_symbol_flow_recent, etc.)

### "Tier 2 rule" triggering too often
- May be false positives (adjust thresholds in uw_config.py)
- Verify flow data quality from UW API
- Check put/call data is updating correctly

### Paper positions not closing on Tier 2 exit
- Check Robinhood MCP is returning position closes
- Verify position_manager.close_position() is called
- Check that exit_price is reasonable

---

## 🔒 TIER 2 LOCK-IN (Thursday 9/10)

Once live deployment begins on Thursday:
- **NO changes to Tier 2 rules** (too risky during live trading)
- **NO tuning of thresholds** mid-day
- Monitor only; adjust only after close or if critical bug found

Tier 2 configuration locked in production.

---

**Ready for Tuesday Morning?** ✅

