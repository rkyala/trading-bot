# Alert Configuration - Sep 7, 2026

## Active Alert Types

### ✅ ENABLED: Fundamentals Analysis
- **Frequency:** 3x daily (9:30 AM, 11:30 AM, 2:30 PM CDT)
- **Content:** Earnings risk, insider activity, analyst changes
- **Destination:** Discord (UW channel)
- **Format:** Consolidated summary (not individual alerts)

### ❌ DISABLED: Futures Monitoring
- **Previous:** ES/NQ/RTY macro context alerts
- **Status:** Stopped (no longer needed)
- **Reason:** User preference - focus on fundamentals

### ❌ DISABLED: Per-Ticker GEX Alerts  
- **Previous:** SPX, SPY, NDX, IWM support/resistance
- **Status:** Stopped (optional monitoring)
- **Reason:** User preference - consolidated only

### ✅ ENABLED: Consolidated Daily Summary
- **Frequency:** Once daily at 4:00 PM CDT
- **Content:**
  - Top 5 earnings-at-risk picks
  - Insider buy/sell activity
  - Key analyst downgrades/upgrades
  - Daily P&L summary
  - Positions open/closed
- **Destination:** Discord (UW channel)
- **Format:** Single detailed embed (not streaming)

---

## Implementation

### Files to Modify

1. **Alert Scheduler** (`uw_bot.py`)
   - Remove futures flow polling
   - Keep fundamentals analysis
   - Add consolidated summary task

2. **Discord Messages** (`uw_discord_gex_alerts.py`)
   - Rename → `uw_consolidated_alerts.py`
   - Remove GEX levels
   - Add fundamentals (earnings, insiders, analysts)

3. **Webhook** 
   - Target: UW Discord channel (single)
   - Webhook URL: Stored in .env.local

---

## Alert Schedule

| Time | Alert | Content |
|------|-------|---------|
| 9:30 AM CDT | Fundamentals | Earnings this week, insider activity |
| 11:30 AM CDT | Fundamentals | Afternoon positioning, key catalysts |
| 2:30 PM CDT | Fundamentals | Power hour risk assessment |
| 4:00 PM CDT | Consolidated Summary | Daily recap, P&L, positions |

---

## Discord Message Format

Single channel, consolidated updates.

Example daily summary:
```
📊 CONSOLIDATED DAILY ALERT

🎯 EARNINGS AT RISK (This Week)
  • NVDA - Wed AH (implied move ±4.2%)
  • MSFT - Thu AH (implied move ±3.8%)
  • TSLA - Fri BTO (implied move ±5.1%)

👤 INSIDER ACTIVITY (Last 24h)
  • AAPL: 3 insider buys (exec team)
  • AMZN: 2 insider sells (profit-taking)
  • GOOG: 1 insider buy (CFO conviction)

📈 ANALYST CHANGES
  • NFLX: Upgraded to Buy (Goldman Sachs)
  • META: Downgraded to Hold (Morgan Stanley)

💰 TODAY'S SUMMARY
  • Trades: 3 entered, 2 exited
  • P&L: +$127.50 (+0.8%)
  • Positions: 5 open, largest NVDA +2.1%
  • Win rate: 4/6 (66.7%)
```

---

## Rationale

**Why Consolidated?**
- Reduces alert fatigue
- Single summary easier to review
- Less notification spam
- Focus on actionable fundamentals

**Why Stop Futures?**
- Macro context less important than stock-specific signals
- Options flow (UW alerts) already captures macro
- Fundamentals > index direction

**Why Fundamentals Only?**
- Highest conviction signals
- Earnings = biggest risk/reward
- Insider trading = conviction meter
- Analyst changes = institutional positioning

---

## Testing

Before Monday 9/8:
```bash
source .env.local
python3 uw_consolidated_alerts.py
# Should send 1 consolidated embed to Discord
```

---

## Status

- ✅ Webhook URL: Secure (.env.local)
- ✅ Channel: New (old compromised)
- ⏳ Consolidation logic: Ready to build
- ⏳ Fundamentals integration: Ready to add

**Ready for Monday deployment**
