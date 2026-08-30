# Day Trading Alerts System - Project Structure

## Overview
Generates 5-minute day trading signals using technical analysis (RSI, Bollinger Bands, MACD, Volume).

## Directory Structure

```
day_trading_alerts/
│
├── .claude-project              # Claude Code project metadata
├── README.md                    # Setup & usage guide
├── STRUCTURE.md                 # This file
├── requirements.txt             # Python dependencies
│
├── alerts_system.py             # Main alerts engine
├── alerts_technical.py          # Technical indicator calculations
├── schwab_quotes.py             # Schwab API integration
│
├── run_alerts_cycle.sh          # Cron job wrapper (executable)
├── schwab_config.json           # API credentials
├── schwab_token.json            # Cached OAuth token (auto-created)
├── alerts_state.json            # Last alert timestamps (prevents spam)
│
├── src/
│   ├── analyzers/
│   │   ├── rsi.py               # RSI calculations
│   │   ├── bollinger.py         # BB calculations
│   │   ├── macd.py              # MACD calculations
│   │   └── volume.py            # Volume analysis
│   │
│   ├── data/
│   │   ├── cache.py             # Data caching logic
│   │   └── storage.py           # State persistence
│   │
│   └── utils/
│       ├── config.py            # Configuration loader
│       └── logger.py            # Logging setup
│
├── tests/
│   ├── test_technical.py        # Technical analysis tests
│   ├── test_signals.py          # Signal generation tests
│   └── test_schwab.py           # API integration tests
│
├── logs/
│   ├── alerts.log               # Main alert log
│   └── errors.log               # Error log
│
└── models/
    └── lstm/                    # (Phase 2) LSTM models directory
        ├── tsla_lstm.pth
        ├── nvda_lstm.pth
        └── ...
```

## Workflow

### Every 5 Minutes (Cron Job)
```
run_alerts_cycle.sh
    ↓
alerts_system.py
    ├─ Load watchlist (TSLA, NVDA, etc.)
    ├─ Fetch price (schwab_quotes.get_quote)
    ├─ Fetch 60 candles (schwab_quotes.get_historical)
    ├─ Calculate signals (alerts_technical.score_signal)
    │   ├─ RSI
    │   ├─ Bollinger Bands
    │   ├─ MACD
    │   └─ Volume
    ├─ Score confidence (0-100)
    ├─ Check cooldown (alerts_state.json)
    └─ Send email (SMTP) if confidence >= 65%
```

## Configuration

### alerts_system.py
```python
WATCHLIST = ["TSLA", "NVDA", ...]      # Stocks to monitor
CONFIDENCE_THRESHOLD = 65              # Min confidence to alert
ALERT_COOLDOWN_MINUTES = 30            # Prevent spam
```

### schwab_config.json
```json
{
  "client_id": "...",
  "client_secret": "...",
  "auth_code": "...",
  "token_url": "...",
  "quotes_url": "..."
}
```

## Cron Setup

```bash
# Edit crontab
crontab -e

# Add this line (every 5 min, 9 AM - 3 PM ET, Mon-Fri)
*/5 9-15 * * 1-5 cd /path/to/day_trading_alerts && ./run_alerts_cycle.sh
```

## Phases

### Phase 1 (Complete) ✅
- Technical signals (RSI, BB, MACD, Volume)
- Email alerts
- Spam prevention

### Phase 2 (Planned)
- LSTM ML predictions
- Weight: Tech 40% + ML 40% + Sentiment 20%
- Improved accuracy

### Phase 3 (Planned)
- Optimize thresholds
- Watchlist management
- Accuracy tracking

## Cost

- **Hosting**: $0 (local Mac)
- **Schwab API**: $0 (shared from bot)
- **Total**: $0/month (Phase 1)

## Related Projects

- `day_trading_alerts_management/` — Dashboard UI for alerts
- `trading_bot/` — Auto-trading bot (separate system)
