# GEX Support/Resistance Discord Alerts

**Status:** ✅ Ready for production

Send daily Discord alerts showing support/resistance levels for major indices.

## Setup

### 1. Set Discord Webhook URL

```bash
export DISCORD_WEBHOOK_URL="https://discordapp.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_TOKEN"
```

Get this from Discord:
- Server Settings → Integrations → Webhooks → New Webhook
- Copy the URL from the webhook

### 2. Manual Test

```bash
export UW_API_KEY="4ac64df9-50c6-4902-a8a4-2ea7e005020b"
export DISCORD_WEBHOOK_URL="your_webhook_url"

python3 unusual_whales_bot/uw_discord_gex_alerts.py
```

### 3. Schedule with Cron

Add to crontab to send alerts at market open (9:30 AM CDT):

```bash
# Market open alerts (9:30 AM CDT = 14:30 UTC, Mon-Fri)
30 14 * * 1-5 cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot && /usr/bin/python3 unusual_whales_bot/uw_discord_gex_alerts.py

# Intraday alerts (11:30 AM CDT = 16:30 UTC)
30 16 * * 1-5 cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot && /usr/bin/python3 unusual_whales_bot/uw_discord_gex_alerts.py

# Power hour alerts (2:30 PM CDT = 19:30 UTC)
30 19 * * 1-5 cd /Users/ramayalala/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot && /usr/bin/python3 unusual_whales_bot/uw_discord_gex_alerts.py
```

### 4. Optional: Integrate into Bot

Add to `uw_bot.py` main loop to send alerts during trading:

```python
from unusual_whales_bot.uw_discord_gex_alerts import GEXDiscordAlerts

# Initialize in __main__
gex_alerts = GEXDiscordAlerts()

# Send every hour during trading hours
if hour == 9 or hour == 11 or hour == 14:  # 9:30 AM, 11:30 AM, 2:30 PM CDT
    await gex_alerts.send_index_alerts(["SPX", "SPY", "NDX", "IWM"])
```

## Alert Format

Each alert shows:
- **Current Price**
- **PUT WALL** (Support level where gamma creates demand)
- **GAMMA FLIP** (Equilibrium/reversal zone)
- **GAMMA MAGNET** (Strongest gamma pin)
- **CALL WALL** (Resistance level where gamma creates supply)
- **Distance to Key Levels** (%)
- **Status** (BREAKDOWN | CONSOLIDATING | TARGET ZONE | BREAKOUT)

### Color Coding

- 🔴 **Red (Breakdown)**: Below PUT WALL
- 🟡 **Orange (Consolidating)**: Below GAMMA FLIP
- 🟢 **Green (Target/Breakout)**: In range or above CALL WALL
- 🔵 **Teal (Stable)**: Normal consolidation

## Indices Covered

| Ticker | Description | Use |
|--------|-------------|-----|
| **SPX** | S&P 500 Index | Macro context |
| **SPY** | S&P 500 ETF | Most common |
| **NDX** | Nasdaq-100 Index | Tech-heavy |
| **IWM** | Russell 2000 Index | Small-cap |

## API Cost

- **per ticker**: 1 API hit
- **per cycle (4 tickers)**: 4 API hits
- **3x daily**: 12 hits/day
- **Daily quota**: 80,000 hits
- **Impact**: 0.015% (negligible)

## Historical Data

GEX levels respond to:
- ✅ Directionalized volume (default, updated intraday)
- ✅ Open interest (can be specified via `source` parameter)

To fetch specific date:
```python
await alerts.get_gex_levels(ticker, date="2026-09-08")
```

## Monitoring

View Discord channel for alerts appearing at:
- 9:30 AM CDT (Market open)
- 11:30 AM CDT (Mid-day)
- 2:30 PM CDT (Power hour)
- 4:00 PM CDT (Market close)

## Troubleshooting

### No alerts sent
- Check Discord webhook URL is set: `echo $DISCORD_WEBHOOK_URL`
- Test manually: `python3 uw_discord_gex_alerts.py`
- Check logs: `tail -f logs/uw_bot_*.log`

### Wrong levels
- GEX updates intraday via directionalized volume
- Early morning levels may differ from mid-day
- Refresh with manual run during market hours

### API rate limit
- Current: 80,000/day (4.8% used)
- Can add 15x more endpoints safely

---

**Status**: Ready for Monday 9/8 deployment ✅

When DISCORD_WEBHOOK_URL is set, alerts auto-send during trading.
