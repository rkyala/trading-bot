# Multi-Stock Trading Bot
**META · MUU · TSLA** — RSI + MACD + VWAP strategy  
Robinhood Agentic account ••••1949 · $500 budget (~$166/stock)

---

## Setup (one time)

### 1. Install Python dependencies
```bash
pip install anthropic yfinance schedule pytz
```

### 2. Set your Anthropic API key
The bot uses Claude AI to execute trades via Robinhood MCP.

**Mac/Linux:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**Windows (Command Prompt):**
```cmd
set ANTHROPIC_API_KEY=sk-ant-...
```

**Windows (PowerShell):**
```powershell
$env:ANTHROPIC_API_KEY="sk-ant-..."
```

> Get your API key at: https://console.anthropic.com/

---

## Run the bot

```bash
python bot.py
```

The bot will:
- Run an immediate scan on startup
- Scan all 3 stocks **every 5 minutes** in sequence
- Only trade during **market hours (9:45 AM – 3:45 PM ET, Mon–Fri)**
- Log everything to `trading_bot.log` and your terminal
- Press **Ctrl+C** to stop cleanly

---

## Trading logic

| Signal | Conditions (need 3 of 4 for BUY, 2 of 4 for SELL) |
|--------|---------------------------------------------------|
| **BUY** | RSI < 30, MACD bullish, price above VWAP, volume ≥ 2× avg |
| **SELL** | RSI > 70, MACD bearish, price below VWAP |
| **Exit** | Stop-loss –3% or take-profit +5% (overrides everything) |

---

## Customise settings

Edit the top of `bot.py`:

```python
RSI_BUY      = 30     # buy when RSI drops below this
RSI_SELL     = 70     # sell when RSI rises above this
STOP_LOSS    = 3.0    # % drop from entry to cut loss
TAKE_PROFIT  = 5.0    # % gain from entry to take profit
SCAN_MINUTES = 5      # how often to scan (minutes)
TOTAL_BUDGET = 500    # total $ across all stocks
```

To add or remove stocks, edit:
```python
STOCKS = ["META", "MUU", "TSLA"]
```

---

## Run automatically at market open (optional)

### Mac — cron job
```bash
crontab -e
```
Add this line (runs at 9:44 AM ET Mon–Fri):
```
44 9 * * 1-5 cd /path/to/trading_bot && ANTHROPIC_API_KEY=sk-ant-... python bot.py >> trading_bot.log 2>&1
```

### Windows — Task Scheduler
1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, 9:44 AM, repeat Mon–Fri
3. Action: Start a program → `python` with argument `C:\path\to\bot.py`

---

## Log output example
```
2026-06-08 09:45:00  INFO     ═══ parallel scan at 09:45 ET ═══
2026-06-08 09:45:01  INFO     ── scanning META ──
2026-06-08 09:45:03  INFO     META  price=$582.40  RSI=28.3  MACD=+1.24  VWAP=$579.10
2026-06-08 09:45:03  INFO     META signal: BUY  (RSI 28.3 oversold, MACD bullish, above VWAP, vol 2.3x)
2026-06-08 09:45:05  INFO     META: sending BUY $166 to Robinhood via Claude AI...
2026-06-08 09:45:08  INFO     META BUY order response: Order placed successfully. Order ID: abc-123...
```

---

## Files
| File | Purpose |
|------|---------|
| `bot.py` | Main bot script |
| `trading_bot.log` | Auto-generated trade log |
| `README.md` | This file |
