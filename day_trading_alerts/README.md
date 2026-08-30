# Day Trading Alerts - Phase 1

Separate project for generating 5-minute day trading signals via technical analysis.

## Architecture

- **Frequency**: Every 5 minutes during market hours (9 AM - 3 PM ET)
- **Execution**: Email alerts only (you decide when to trade)
- **Data Source**: Schwab real-time quotes API
- **Signals**: RSI, Bollinger Bands, MACD, Volume
- **Cost**: ~$2-5/month (Schwab API only)

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Email
Edit `alerts_system.py` and update:
```python
EMAIL_CONFIG = {
    "sender_email": "your_email@gmail.com",
    "sender_password": "your_app_password",  # Gmail app password, not your main password
    "recipient_email": "kris.yalala@yahoo.com"
}
```

### 3. Update Watchlist
In `alerts_system.py`:
```python
WATCHLIST = ["TSLA", "NVDA", "AAPL", ...]  # Add your tickers
```

### 4. Test Manually
```bash
python alerts_system.py
```

You should see:
- Schwab auth (token caching)
- Scan results for each symbol
- Email alert if confidence >= 65%

### 5. Setup Cron Job
```bash
# Make script executable
chmod +x run_alerts_cycle.sh

# Edit crontab
crontab -e

# Add this line (runs every 5 min, 9 AM - 3 PM ET, Mon-Fri)
*/5 9-15 * * 1-5 cd /path/to/day_trading_alerts && ./run_alerts_cycle.sh
```

## Files

- `alerts_system.py` - Main engine (scan + email)
- `alerts_technical.py` - Technical indicator calculations
- `schwab_quotes.py` - Schwab API wrapper
- `schwab_config.json` - API credentials (shared from trading_bot)
- `schwab_token.json` - Cached OAuth token (auto-created)
- `alerts_state.json` - Last alert timestamps (prevents spam)
- `run_alerts_cycle.sh` - Cron wrapper script
- `logs/alerts.log` - Detailed logs

## Signal Scoring

Each symbol is scored 0-100 based on:

| Component | Weight | Conditions |
|-----------|--------|-----------|
| RSI < 30 (Oversold) | +30 | Bullish reversal |
| RSI > 70 (Overbought) | +15 | Bearish reversal |
| Price at Lower BB | +25 | Support level |
| Price at Upper BB | +20 | Resistance level |
| MACD Bullish Cross | +20 | Momentum up |
| Volume Spike (1.5x) | +10 | Confirmation |

**Alert Threshold**: 65% confidence minimum

**Cooldown**: 30 minutes per symbol (prevent alert spam)

## Example Alert Email

```
Subject: 🟢 3 Day Trading Alert(s) - 10:35 AM

SYMBOL | PRICE   | CONFIDENCE | SIGNAL
TSLA   | $234.50 | 78%        | RSI 28 (Oversold) | BB Lower Band | Volume Spike
NVDA   | $115.20 | 72%        | RSI 32 (Oversold) | MACD Bullish
AMD    | $92.50  | 68%        | BB Lower Band | Volume Spike
```

## Roadmap

**Phase 1** (Current - Technical Only) - Complete ✅
- RSI, BB, MACD, Volume signals
- Email alerts
- Spam prevention

**Phase 2** (Week 2 - Add ML) - Coming
- Integrate LSTM predictions
- Weight: Tech 40% + ML 40% + Sentiment 20%
- Improved accuracy

**Phase 3** (Week 3 - Optimization)
- Tune confidence thresholds
- Add watchlist management
- Track alert accuracy

## Cost

| Component | Cost |
|-----------|------|
| Hosting | $0 (local Mac) |
| Schwab API | $0 (shared from bot) |
| Email (SMTP) | $0 (Gmail) |
| **Total** | **$0/month** |

## Comparison: Trading Bot vs Alerts

| Feature | Trading Bot | Alerts System |
|---------|-------------|---------------|
| Frequency | 15 min (swing) | 5 min (day) |
| Execution | Auto (MCP) | Manual (email) |
| Hold time | 1-3 days | 30-60 min |
| Daily profit | +$22-25 | +$10-50 (your trades) |
| Risk | Medium (real capital) | None (alerts only) |

## Troubleshooting

### No emails being sent
1. Check Gmail is allowing less secure apps or use app password
2. Check `logs/alerts.log` for errors
3. Verify recipient email in config

### No candles fetched
1. Check Schwab token expiration
2. Verify API credentials in `schwab_config.json`
3. Check market hours (alerts only work 9 AM - 3 PM ET)

### Too many/too few alerts
Adjust `CONFIDENCE_THRESHOLD` in `alerts_system.py`:
- Lower = more alerts (60%)
- Higher = fewer alerts (75%)

## Support

Check logs in `logs/alerts.log` for detailed execution info.
