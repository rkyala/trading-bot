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

### 3. Email notifications (optional but recommended)
The bot emails fills, halts, and reconciliation changes. Set SMTP credentials
(e.g. a Gmail or Yahoo app password — not your account password):

```bash
export SMTP_HOST="smtp.mail.yahoo.com"   # or smtp.gmail.com
export SMTP_PORT="587"
export SMTP_USER="you@yahoo.com"
export SMTP_PASS="your-app-password"
export NOTIFY_EMAIL="kris.yalala@yahoo.com"   # default if unset
```

Without these, notifications are written to the log only.

---

## Safety rails

- **Startup reconciliation** — on boot the bot fetches actual Robinhood
  positions and syncs `positions.json`: holdings it doesn't know about are
  adopted (universe symbols only), locally-tracked positions that no longer
  exist are dropped. Cloud restarts can't orphan a position.
- **Auth-failure halt** — if Robinhood rejects auth, the bot stops trading,
  emails you, and stays halted until `ROBINHOOD_TOKEN` is replaced (a new
  token clears the halt automatically on restart).
- **Daily loss limit** — if the day's P&L falls below −3% of the budget
  (`DAILY_LOSS_LIMIT_PCT`), no new entries for the rest of the day; stops on
  open positions stay active. Resets at the next trading day.

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

Signals are computed deterministically in `bot.py` (same math as `backtest_v2.py`,
so live behavior matches the backtest). Claude is only used to execute orders
via the Robinhood MCP. Two strategies, selected by `STRATEGY` in `bot.py`:

| Strategy | Entry | Exit |
|----------|-------|------|
| **momentum** (default) | price > 30d VWAP, MACD > 0, volume ≥ 2× 10d avg | stop starts −3% below entry, trails 5% below the highest price since entry |
| **meanrev** | RSI < 30 and price < 30d VWAP | −3% stop, or RSI recovers above 50 |

Open positions are tracked in `positions.json` so state survives restarts.

Backtested 2024-06 → 2026-06 ($500 budget, no slippage modeled):
momentum +9.9% (max DD −6.4%), meanrev +73.5% (max DD −22%, concentrated in a
few crash-bounces — fragile in bear markets). See `backtest_v2.py` to rerun.

---

## Customise settings

Edit the top of `bot.py`:

```python
STRATEGY     = "momentum"  # "momentum" or "meanrev"
STOP_LOSS    = 0.03    # initial stop, fraction below entry
TRAIL_PCT    = 0.05    # momentum: trail % below peak since entry
RSI_BUY      = 30      # meanrev: buy when RSI drops below this
RSI_EXIT     = 50      # meanrev: sell when RSI recovers above this
VOL_RATIO    = 2.0     # momentum: required volume vs 10d average
SCAN_MINUTES = 5       # how often to scan (minutes)
TOTAL_BUDGET = 500     # total $ across all stocks
```

To add or remove stocks, edit:
```python
SYMBOLS = ["META", "MU", "TSLA", "NVDA", "SOXL", "SPXL", "NVDL"]
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
