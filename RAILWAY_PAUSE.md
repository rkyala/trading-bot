# ⏸️ Railway Bot Pause

## Status: PAUSED

**Start Date**: August 18, 2026
**Reason**: Week-long local dry-run validation (Aug 19-23)
**Expected Resume**: August 26, 2026 (after week completes & results validated)

---

## Why Paused?

Running concurrent bots on Railway + local Mac creates:
- ❌ Duplicate order execution
- ❌ Conflicting signals (Llama vs FinRL differences)
- ❌ Inaccurate performance metrics
- ❌ Position overwrites

---

## Local Bot Running Instead

✅ **Local Machine (Mac)**
- Llama 3.2 3B (local inference, zero API cost)
- Enhanced system: Technical + RAG + Ensemble
- Dry-run mode: Hypothetical trades only
- Duration: Mon 8/19 - Fri 8/23
- Expected: 20-30 trades, 55-65% win rate

---

## Resumption Criteria

**Will resume live trading on 8/26 if:**
1. ✅ Local dry-run win rate ≥ 55%
2. ✅ Avg confidence ≥ 60%
3. ✅ No system errors
4. ✅ Total profit ≥ +$25

**Will NOT resume if:**
- ❌ Any of above criteria not met
- ❌ Needs parameter adjustment
- ❌ Needs extended validation

---

## How to Resume

After Friday 8/23 results:

```bash
# Check weekly report
cat weekly_backtest_report.json

# If approved, restart Railway
railway up --env production

# Or via Railway dashboard:
# Settings > Redeploy > Latest version
```

---

## Notes

- Robinhood MCP connection: **READY** (tested July 24)
- Stage 3 execution: **LOCKED** (no changes needed)
- Position dedup: **FIXED** (Aug 7 commit)
- 401 retry logic: **ACTIVE** (Aug 12 fix)

---

**Last Status Update**: August 18, 2026 @ 2:30 PM CDT
**Next Action**: Review local results Friday 8/23 @ 4:30 PM CDT
