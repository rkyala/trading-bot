"""
Autonomous AI Trading Bot
Claude runs the full trading loop — stock selection, analysis,
signal generation, and trade execution via the Robinhood MCP server.
Python is just a scheduler.
"""

import anthropic
import yfinance as yf
import requests
import schedule
import time
import logging
import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger(__name__)

ET           = ZoneInfo("America/New_York")
ACCT         = "432591949"
SCAN_MINUTES = 5
MAX_POSITION = 125   # max $ per position
TOTAL_BUDGET = 500
DAILY_LOSS_LIMIT_PCT = 5.0   # halt new buys if equity drops this % from day-start
STATE_PATH = os.path.join(os.environ.get("DATA_DIR", "."), "bot_state.json")

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    log.error("ANTHROPIC_API_KEY not set. Exiting.")
    sys.exit(1)

# Robinhood auth — two modes:
#   OAuth (preferred): RH_CLIENT_ID + RH_REFRESH_TOKEN, bot mints access tokens
#   itself (run get_token.py once to obtain these).
#   Static (legacy): ROBINHOOD_TOKEN, expires after ~4 days.
RH_CLIENT_ID     = os.environ.get("RH_CLIENT_ID", "")
RH_REFRESH_TOKEN = os.environ.get("RH_REFRESH_TOKEN", "")
rh_token         = os.environ.get("ROBINHOOD_TOKEN", "")
RH_TOKEN_URL     = "https://api.robinhood.com/oauth2/token/"
TOKEN_FILE       = os.path.join(os.environ.get("DATA_DIR", "."), "rh_token.json")

if RH_CLIENT_ID and RH_REFRESH_TOKEN:
    log.info("Robinhood auth: OAuth refresh mode")
elif rh_token:
    log.warning("Robinhood auth: static ROBINHOOD_TOKEN (expires ~4 days) — "
                "run get_token.py and set RH_CLIENT_ID/RH_REFRESH_TOKEN instead.")
else:
    log.warning("No Robinhood credentials set — trades will fail auth.")

client = anthropic.Anthropic(api_key=api_key)

# ── Robinhood token management ──────────────────────────────────────────────

_tok = {"access": None, "expires_at": 0.0, "refresh": None}


def _can_refresh():
    return bool(RH_CLIENT_ID and (RH_REFRESH_TOKEN or _tok["refresh"]))


def get_rh_access_token(force_refresh=False):
    """Returns a valid access token, refreshing via OAuth when possible."""
    if not _can_refresh():
        return rh_token or None  # static mode

    if _tok["access"] is None:  # warm cache from disk (survives restarts w/ volume)
        try:
            with open(TOKEN_FILE) as f:
                saved = json.load(f)
            _tok.update({k: saved.get(k, _tok[k]) for k in _tok})
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if not force_refresh and _tok["access"] and time.time() < _tok["expires_at"] - 600:
        return _tok["access"]

    for refresh in dict.fromkeys([_tok["refresh"] or "", RH_REFRESH_TOKEN]):
        if not refresh:
            continue
        try:
            r = requests.post(RH_TOKEN_URL, data={
                "grant_type":    "refresh_token",
                "refresh_token": refresh,
                "client_id":     RH_CLIENT_ID,
            }, timeout=20)
            if r.status_code != 200:
                log.error("Token refresh failed: %s %s", r.status_code, r.text[:200])
                continue
            d = r.json()
            _tok["access"]     = d["access_token"]
            _tok["expires_at"] = time.time() + float(d.get("expires_in", 3600))
            if d.get("refresh_token"):
                _tok["refresh"] = d["refresh_token"]
            try:
                with open(TOKEN_FILE, "w") as f:
                    json.dump(_tok, f)
            except OSError as exc:
                log.warning("Could not persist token cache: %s", exc)
            log.info("Robinhood access token refreshed (valid ~%.0fh)",
                     float(d.get("expires_in", 0)) / 3600)
            return _tok["access"]
        except Exception as exc:
            log.error("Token refresh error: %s", exc)
    return None


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
    close_ = now.replace(hour=15, minute=45, second=0, microsecond=0)
    return open_ <= now <= close_


def load_state() -> dict:
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_PATH, "w") as f:
            json.dump(state, f)
    except Exception as exc:
        log.warning("Could not save state: %s", exc)


def check_daily_loss(equity: float) -> tuple[bool, str]:
    """Returns (halted, status_message). Resets day-start equity each new ET day."""
    state = load_state()
    today = datetime.now(ET).strftime("%Y-%m-%d")

    if state.get("date") != today:
        state = {"date": today, "day_start_equity": equity}
        save_state(state)
        return False, f"New trading day. Day-start equity recorded: ${equity:,.2f}"

    start_equity = state.get("day_start_equity", equity)
    if start_equity <= 0:
        return False, "Day-start equity is zero — skipping loss check."

    change_pct = (equity - start_equity) / start_equity * 100
    if change_pct <= -DAILY_LOSS_LIMIT_PCT:
        return True, (
            f"DAILY LOSS LIMIT HIT: equity ${equity:,.2f} is {change_pct:.2f}% "
            f"below day-start ${start_equity:,.2f} (limit -{DAILY_LOSS_LIMIT_PCT}%)."
        )
    return False, f"Day P&L: {change_pct:+.2f}% (start ${start_equity:,.2f}, now ${equity:,.2f})"


# ── Tool implementations ──────────────────────────────────────────────────────

def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        d = prices[i] - prices[i - 1]
        if d > 0: gains += d
        else:     losses += abs(d)
    avg_g = gains / period
    avg_l = losses / period or 1e-9
    return round(100 - 100 / (1 + avg_g / avg_l), 2)


def calc_ema(prices, period):
    if len(prices) < period:
        return prices[-1]
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 4)


def tool_fetch_market_data(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="30d", interval="1d")
        if hist.empty or len(hist) < 14:
            return {"error": f"Not enough history for {symbol}"}
        prices  = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()
        n       = min(len(prices), len(volumes))
        vwap    = round(sum(prices[i] * volumes[i] for i in range(n)) / (sum(volumes[:n]) or 1), 4)
        avg_vol = sum(volumes[-10:]) / 10
        info    = ticker.fast_info
        return {
            "symbol":       symbol,
            "price":        round(prices[-1], 2),
            "prev_close":   round(prices[-2], 2),
            "rsi":          calc_rsi(prices),
            "macd":         round(calc_ema(prices, 12) - calc_ema(prices, 26), 4),
            "vwap":         vwap,
            "ema9":         calc_ema(prices, 9),
            "ema20":        calc_ema(prices, 20),
            "volume_ratio": round(volumes[-1] / avg_vol, 2) if avg_vol else 1,
            "market_cap":   getattr(info, "market_cap",  None),
            "pe_ratio":     getattr(info, "pe_ratio",    None),
            "52w_high":     getattr(info, "year_high",   None),
            "52w_low":      getattr(info, "year_low",    None),
        }
    except Exception as exc:
        return {"error": str(exc)}


def tool_get_trending_stocks() -> dict:
    try:
        url  = "https://query1.finance.yahoo.com/v1/finance/trending/US"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        quotes = resp.json()["finance"]["result"][0]["quotes"]
        syms   = [q["symbol"].upper() for q in quotes[:20]
                  if q.get("symbol", "").replace("-", "").isalpha()]
        return {"trending": syms}
    except Exception as exc:
        return {"error": str(exc), "trending": ["SOXL", "NVDL", "SPXL", "NVDA", "TSLA"]}


def tool_get_news(symbol: str) -> dict:
    try:
        news = yf.Ticker(symbol).news or []
        return {"symbol": symbol, "headlines": [n.get("title", "") for n in news[:5]]}
    except Exception as exc:
        return {"error": str(exc), "headlines": []}


TOOLS = [
    {
        "name": "fetch_market_data",
        "description": (
            "Fetch technical indicators for a stock: price, RSI, MACD, VWAP, EMA9/20, "
            "volume ratio, market cap, P/E. Use before any trade decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "get_trending_stocks",
        "description": "Return a list of currently trending US stock symbols from Yahoo Finance.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_news",
        "description": "Return recent news headlines for a stock symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
]


def dispatch_tool(name: str, inp: dict) -> str:
    if name == "fetch_market_data":
        return json.dumps(tool_fetch_market_data(inp["symbol"]))
    if name == "get_trending_stocks":
        return json.dumps(tool_get_trending_stocks())
    if name == "get_news":
        return json.dumps(tool_get_news(inp["symbol"]))
    return json.dumps({"error": f"unknown tool {name}"})


def fetch_portfolio_equity():
    """Ask Claude (via Robinhood MCP) for current total portfolio equity. Returns float or None."""
    for attempt in (1, 2):
        token = get_rh_access_token(force_refresh=(attempt == 2))
        if not token:
            log.warning("Could not fetch portfolio equity: no Robinhood access token")
            return None
        try:
            resp = client.beta.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                betas=["mcp-client-2025-04-04"],
                system=(
                    f"You are a read-only assistant for Robinhood account {ACCT}. "
                    "Call get_portfolio (or equivalent) and reply with ONLY the total "
                    "equity as a plain number, e.g. 512.34. No words, no symbols."
                ),
                mcp_servers=[
                    {
                        "type": "url",
                        "url":  "https://agent.robinhood.com/mcp/trading",
                        "name": "Rh",
                        "authorization_token": token,
                    }
                ],
                messages=[{"role": "user", "content": "What is the total portfolio equity?"}],
            )
            text = " ".join(b.text for b in resp.content if hasattr(b, "text"))
            import re
            m = re.search(r"[\d,]+\.?\d*", text)
            if m:
                return float(m.group().replace(",", ""))
            return None
        except anthropic.BadRequestError as exc:
            if "Authentication error" in str(exc) and attempt == 1 and _can_refresh():
                log.warning("MCP auth failed fetching equity — force-refreshing token and retrying once")
                continue
            log.warning("Could not fetch portfolio equity: %s", exc)
            return None
        except Exception as exc:
            log.warning("Could not fetch portfolio equity: %s", exc)
            return None
    return None


# ── Main agentic loop ─────────────────────────────────────────────────────────

def run_trading_loop():
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return

    now = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    log.info("\u2550\u2550\u2550 Autonomous trading run at %s \u2550\u2550\u2550", now)

    # \u2500\u2500 Daily loss limit check \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    equity = fetch_portfolio_equity()
    if equity is not None:
        halted, status_msg = check_daily_loss(equity)
    else:
        halted, status_msg = False, "Equity unavailable \u2014 skipping loss check."
    log.info("Loss-limit check: %s", status_msg)

    trading_clause = ""
    if halted:
        trading_clause = (
            f"\n\n*** {status_msg} ***\n"
            "TRADING HALTED FOR NEW ENTRIES TODAY. Do NOT place any new BUY orders.\n"
            "You may still call get_equity_positions and place SELL orders to manage "
            "or exit existing positions (e.g. stop-losses), but place no new buys."
        )
    # \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

    system = f"""You are an aggressive, autonomous day-trading agent with full control over a Robinhood brokerage account.

Account : {ACCT} (cash, agentic-enabled)
Budget  : ${TOTAL_BUDGET} total | max ${MAX_POSITION} per position
Time    : {now}
{status_msg}

PHILOSOPHY: This account exists to trade actively. Cash sitting idle is a missed
opportunity, not a "safe" choice. You should bias toward action over inaction.
HOLD is a valid choice only when you've genuinely found nothing — not a default.

Each run you must:
1. Call get_equity_positions (Robinhood MCP) to see current holdings and cash available.
2. Call get_trending_stocks to discover candidates, then get_news + fetch_market_data
   on at least 3-5 of them.
3. Apply momentum/mean-reversion logic liberally:
   - RSI < 40 or bouncing off VWAP/EMA support -> consider BUY
   - RSI > 65 or a held position up >3% -> consider taking profit (SELL)
   - A held position down >3% -> consider cutting the loss (SELL)
   - Strong volume spike + positive news -> consider BUY even if RSI is neutral
4. If you have idle cash and at least one candidate clears a reasonable bar
   (don't require perfection on all signals - 2 out of 3 aligned is enough),
   PLACE THE TRADE. Call review_equity_order, and then IMMEDIATELY call
   place_equity_order yourself in the same turn — do not stop after the
   review to ask for confirmation. There is no human watching this session;
   you are fully authorized to execute trades autonomously. An order is not
   "placed" until place_equity_order has actually been called and returned
   a result.
5. Only trade stocks with market cap > $500M. Never exceed ${MAX_POSITION} per position,
   and never invest more than you have in cash.
6. Think out loud with specific numbers (RSI, price, % change) for every decision.

Default posture: look for a reason TO trade, not a reason not to. If multiple
candidates look reasonable, trade the best one rather than waiting for a perfect setup.{trading_clause}"""

    messages = [
        {"role": "user", "content": "Run your trading analysis now and execute any trades you identify."}
    ]

    force_refresh = False
    auth_retries = 0
    while True:
        token = get_rh_access_token(force_refresh=force_refresh)
        if not token:
            log.error("No Robinhood access token available — aborting run.")
            break
        force_refresh = False
        try:
            resp = client.beta.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                betas=["mcp-client-2025-04-04"],
                system=system,
                mcp_servers=[
                    {
                        "type": "url",
                        "url":  "https://agent.robinhood.com/mcp/trading",
                        "name": "Rh",
                        "authorization_token": token,
                    }
                ],
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.BadRequestError as exc:
            if "Authentication error" in str(exc) and _can_refresh() and auth_retries == 0:
                log.warning("MCP auth failed — force-refreshing token and retrying once")
                force_refresh = True
                auth_retries += 1
                continue
            log.error("MCP request failed: %s", exc)
            break

        for block in resp.content:
            if hasattr(block, "text") and block.text:
                log.info("Claude: %s", block.text[:800])

        if resp.stop_reason == "end_turn":
            log.info("Trading run complete.")
            break

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    log.info("-> tool: %s  input: %s", block.name, json.dumps(block.input)[:120])
                    result = dispatch_tool(block.name, block.input)
                    log.info("<- result: %s", result[:200])
                    tool_results.append({
                        "type":        "tool_result",
                        "tool_use_id": block.id,
                        "content":     result,
                    })
            messages = messages + [
                {"role": "assistant", "content": resp.content},
                {"role": "user",      "content": tool_results},
            ]
        else:
            log.info("Stop reason: %s -- ending loop.", resp.stop_reason)
            break


def main():
    log.info("Autonomous AI Trading Bot starting -- Claude runs the full loop")
    log.info("Scan interval: %d min | Account: %s | Budget: $%d",
             SCAN_MINUTES, ACCT, TOTAL_BUDGET)

    schedule.every(SCAN_MINUTES).minutes.do(run_trading_loop)

    log.info("Running first loop immediately...")
    run_trading_loop()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot stopped.")
        sys.exit(0)
