# UW Bot Cron Schedule Setup

## Quick Start

Add to crontab for 8:30 AM CDT (= 9:30 AM UTC / 1:30 PM UTC):

```bash
# For recurring daily (Mon-Fri 8:30 AM CDT):
(crontab -l 2>/dev/null; echo "30 08 * * 1-5 /Users/ramayalala/Documents/Documents\\ -\\ Rama\\'s\\ MacBook\\ Pro/trading_bot/start_uw_bot.sh") | crontab -
```

Or manually:
```bash
crontab -e
# Add line: 30 08 * * 1-5 /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot/start_uw_bot.sh
# Save and exit
```

---

## Time Zone

**Mac cron uses local time**
- If Mac is set to **CDT**: use `30 08` for 8:30 AM CDT ✅
- If Mac is set to **UTC**: use `30 13` for 8:30 AM CDT

Check your Mac's timezone:
```bash
date
# Example: Mon Sep 8 08:30:00 CDT 2026
```

---

## Cron Explanation

```
30 08 * * 1-5 /path/to/start_uw_bot.sh
│  │  │ │ │
│  │  │ │ └─ Day of week (1=Mon, 5=Fri)
│  │  │ └─── Month (*)
│  │  └───── Day of month (*)
│  └──────── Hour (08 = 8 AM local time)
└─────────── Minute (30)
```

**For 8:30 AM CDT:**
- `30 08 * * 1-5` (if Mac timezone = CDT)
- `30 13 * * 1-5` (if Mac timezone = UTC)

---

## Tuesday 9/8 Only

For one-time run (just Tuesday):
```bash
30 08 08 09 2 /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot/start_uw_bot.sh
```

---

## Verify

Is cron job added?
```bash
crontab -l | grep uw_bot
```

Is script executable?
```bash
ls -la start_uw_bot.sh
# Should show: -rwxr-xr-x
```

---

## Monitor On Tuesday

```bash
# Watch logs
tail -f logs/uw_bot_*.log

# Check if running
ps aux | grep uw_bot | grep -v grep

# Stop if needed
kill <PID>
```

---

## Environment Variables

The start script uses:
- `UW_API_KEY="<UW_API_KEY_REDACTED — read it from .env.local, never inline>"` ✅
- `RH_CLIENT_ID` and `RH_REFRESH_TOKEN` (from environment)
- `DISCORD_WEBHOOK_URL` (from environment)

Make sure RH tokens are set in your shell before 8:30 AM:
```bash
export RH_CLIENT_ID="your_client_id"
export RH_REFRESH_TOKEN="your_refresh_token"
```

---

## Status

✅ Script ready: `start_uw_bot.sh`
⏳ Cron job: Add with commands above
🟢 API key: Configured
⚠️  Robinhood tokens: Verify before 8:30 AM

Ready for Tuesday 9/8 9:35 AM market open (8:30 AM pre-market) ✅
