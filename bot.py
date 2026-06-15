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
import smtplib
import time
import logging
import os
import sys
import json
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import rl_policy

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
MIN_PRICE = 5.0   # no penny stocks
STOP_LOSS_PCT   = 3.0   # hard stop: sell if down this much from entry
PROFIT_LOCK_PCT = 3.0   # once up this much from entry, start trailing
TRAIL_PCT       = 2.0   # trailing stop distance from the high-water mark
MIN_POSITION    = 50    # smallest position size for a low-conviction entry
COOLDOWN_MINUTES = 30   # don't re-enter a symbol this soon after exiting it
STATE_PATH = os.path.join(os.environ.get("DATA_DIR", "."), "bot_state.json")

# Email alerts (requires SMTP_HOST / SMTP_USER / SMTP_PASS env vars; logs otherwise)
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "kris.yalala@yahoo.com")
SMTP_HOST    = os.environ.get("SMTP_HOST", "")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")

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


# ── Notifications ────────────────────────────────────────────────────────────

TRADE_LOG = []  # accumulated trades since the last hourly email


def notify(subject, body):
    log.info("NOTIFY: %s | %s", subject, body.replace("\n", " ")[:300])
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        log.warning("Email not configured (set SMTP_HOST/SMTP_USER/SMTP_PASS) — "
                    "notification logged only.")
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[trading-bot] {subject}"
        msg["From"]    = SMTP_USER
        msg["To"]      = NOTIFY_EMAIL
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception as exc:
        log.error("Email send failed: %s", exc)


def send_trade_summary():
    """Hourly consolidated email of trades placed since the last summary."""
    if not TRADE_LOG:
        log.info("Hourly summary: no trades to report.")
        return
    lines = [
        f"{t['time']}  {t['side'].upper():4s} {t['symbol']:6s} "
        f"qty={t['quantity']}  type={t['type']}"
        + (f"  limit=${t['price']}" if t.get("price") else "")
        for t in TRADE_LOG
    ]
    body = f"{len(TRADE_LOG)} trade(s) in the last hour:\n\n" + "\n".join(lines)
    notify("Hourly trade summary", body)
    TRADE_LOG.clear()


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
    close_ = now.replace(hour=16, minute=0, second=0, microsecond=0)
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


def record_trade(state: dict, trade: dict) -> None:
    """Append a placed trade to persistent history for the performance-feedback loop,
    and track entry price / high-water mark per symbol for trailing-stop checks."""
    history = state.setdefault("trade_history", [])
    history.append({
        "symbol":   trade.get("symbol"),
        "side":     trade.get("side"),
        "quantity": trade.get("quantity"),
        "price":    trade.get("price"),
        "time":     trade.get("time"),
    })
    state["trade_history"] = history[-500:]  # cap growth

    sym   = trade.get("symbol")
    side  = (trade.get("side") or "").lower()
    price = trade.get("price")
    positions = state.setdefault("positions", {})
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None

    if sym and side == "buy" and price:
        # New entry (or re-entry) — reset tracking for this symbol, and record
        # the market state at entry so a later sell can do an online Q-update.
        entry_state = None
        ind = get_indicators(sym)
        if ind:
            entry_state = rl_policy.discretize(
                rsi=ind["rsi"], macd=ind["macd"], price=ind["price"],
                vwap=ind["vwap"], volume_ratio=ind["volume_ratio"], holding=False,
            )
        sector = None
        try:
            sector = (yf.Ticker(sym).info or {}).get("sector")
        except Exception:
            pass
        positions[sym] = {"entry_price": price, "high_water_mark": price,
                           "entry_state": entry_state, "sector": sector}
    elif sym and side == "sell":
        cooldowns = state.setdefault("cooldowns", {})
        cooldowns[sym] = time.time()
        pos = positions.pop(sym, None)
        if pos and pos.get("entry_state") and price:
            entry_price = pos.get("entry_price")
            if entry_price:
                reward = (price - entry_price) / entry_price
                ind = get_indicators(sym)
                next_state = (
                    rl_policy.discretize(
                        rsi=ind["rsi"], macd=ind["macd"], price=ind["price"],
                        vwap=ind["vwap"], volume_ratio=ind["volume_ratio"], holding=False,
                    ) if ind else pos["entry_state"]
                )
                rl_policy.update_q(pos["entry_state"], "BUY", reward, next_state)
                log.info("RL online update: state=%s action=BUY reward=%.4f next_state=%s",
                         pos["entry_state"], reward, next_state)

    save_state(state)


def get_indicators(symbol: str):
    """Lightweight indicator snapshot for RL state discretization (price, RSI, MACD, VWAP, volume ratio)."""
    try:
        hist = yf.Ticker(symbol).history(period="30d", interval="1d")
        if hist.empty or len(hist) < 14:
            return None
        prices  = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()
        n       = min(len(prices), len(volumes))
        vwap    = sum(prices[i] * volumes[i] for i in range(n)) / (sum(volumes[:n]) or 1)
        avg_vol = sum(volumes[-10:]) / 10
        return {
            "price":        prices[-1],
            "rsi":          calc_rsi(prices),
            "macd":         calc_ema(prices, 12) - calc_ema(prices, 26),
            "vwap":         vwap,
            "volume_ratio": volumes[-1] / avg_vol if avg_vol else 1,
        }
    except Exception:
        return None


def get_current_price(symbol: str):
    try:
        fi = yf.Ticker(symbol).fast_info
        price = fi.get("lastPrice") if hasattr(fi, "get") else getattr(fi, "last_price", None)
        return float(price) if price else None
    except Exception:
        return None


def check_trailing_stops(state: dict) -> list[str]:
    """Mechanically check tracked positions against stop-loss / trailing-stop rules.

    Updates each position's high-water mark in state, and returns a list of
    human-readable instructions for symbols that must be sold this run
    (hard stop-loss hit, or price pulled back from its high by TRAIL_PCT after
    having locked in PROFIT_LOCK_PCT gain).
    """
    positions = state.get("positions", {})
    if not positions:
        return []

    forced_sells = []
    changed = False
    for sym, pos in list(positions.items()):
        price = get_current_price(sym)
        if not price:
            continue

        entry = pos.get("entry_price", price)
        hwm   = pos.get("high_water_mark", entry)
        if price > hwm:
            pos["high_water_mark"] = price
            hwm = price
            changed = True

        change_pct = (price - entry) / entry * 100
        drop_from_hwm_pct = (hwm - price) / hwm * 100 if hwm else 0

        if change_pct <= -STOP_LOSS_PCT:
            forced_sells.append(
                f"{sym}: STOP-LOSS HIT — down {change_pct:.2f}% from entry ${entry:.2f} "
                f"(current ${price:.2f}). SELL this position now."
            )
        elif change_pct >= PROFIT_LOCK_PCT and drop_from_hwm_pct >= TRAIL_PCT:
            forced_sells.append(
                f"{sym}: TRAILING STOP HIT — up {change_pct:.2f}% from entry ${entry:.2f}, "
                f"but pulled back {drop_from_hwm_pct:.2f}% from its high ${hwm:.2f} to "
                f"${price:.2f}. SELL this position now to lock in the gain."
            )

    if changed:
        state["positions"] = positions
        save_state(state)

    return forced_sells


def cooldown_summary(state: dict) -> str:
    """List symbols recently sold that are still within their re-entry cooldown."""
    cooldowns = state.get("cooldowns", {})
    if not cooldowns:
        return ""

    now = time.time()
    active = []
    for sym, sold_at in cooldowns.items():
        remaining = COOLDOWN_MINUTES - (now - sold_at) / 60
        if remaining > 0:
            active.append(f"{sym} ({remaining:.0f} min left)")

    if not active:
        return ""
    return (
        f"Recently exited, in cooldown — do NOT re-buy these symbols yet "
        f"(min {COOLDOWN_MINUTES} min between exit and re-entry to avoid churn): "
        + ", ".join(active)
    )


def sector_exposure_summary(state: dict) -> str:
    """Summarize current open positions by sector, for diversification awareness."""
    positions = state.get("positions", {})
    if not positions:
        return "No open positions."

    by_sector = {}
    for sym, pos in positions.items():
        sector = pos.get("sector") or "Unknown"
        by_sector.setdefault(sector, []).append(sym)

    lines = [f"{sector}: {', '.join(syms)}" for sector, syms in by_sector.items()]
    summary = "Current sector exposure — " + "; ".join(lines)

    concentrated = [s for s, syms in by_sector.items() if s != "Unknown" and len(syms) >= 2]
    if concentrated:
        summary += (
            f". NOTE: already {len(by_sector[concentrated[0]])} positions in "
            f"{concentrated[0]} — avoid adding another position in this sector "
            "unless the setup is exceptional; prefer diversifying into a different sector."
        )
    return summary


def symbol_performance_summary(state: dict, top_n: int = 4) -> str:
    """Compute realized P&L per symbol via FIFO matching of buy/sell quantities.

    This is a simple feedback loop (not true RL): symbols that have been
    consistently losing money are surfaced so the agent can deprioritize them,
    and consistent winners are surfaced so the agent can keep favoring them.
    """
    history = state.get("trade_history", [])
    if not history:
        return ""

    open_lots = {}   # symbol -> list of (qty, price) buy lots not yet sold
    realized  = {}   # symbol -> {"pnl": float, "trades": int}

    for t in history:
        sym = t.get("symbol")
        side = (t.get("side") or "").lower()
        qty = t.get("quantity")
        price = t.get("price")
        try:
            qty = float(qty)
            price = float(price)
        except (TypeError, ValueError):
            continue
        if not sym or qty <= 0 or price <= 0:
            continue

        lots = open_lots.setdefault(sym, [])
        if side == "buy":
            lots.append([qty, price])
        elif side == "sell":
            remaining = qty
            pnl = 0.0
            while remaining > 0 and lots:
                lot_qty, lot_price = lots[0]
                matched = min(lot_qty, remaining)
                pnl += matched * (price - lot_price)
                lot_qty -= matched
                remaining -= matched
                if lot_qty <= 1e-9:
                    lots.pop(0)
                else:
                    lots[0][0] = lot_qty
            if pnl != 0.0:
                r = realized.setdefault(sym, {"pnl": 0.0, "trades": 0})
                r["pnl"] += pnl
                r["trades"] += 1

    if not realized:
        return ""

    ranked = sorted(realized.items(), key=lambda kv: kv[1]["pnl"])
    losers = [f"{s} (${d['pnl']:+.2f} over {d['trades']} round-trip(s))"
              for s, d in ranked[:top_n] if d["pnl"] < 0]
    winners = [f"{s} (${d['pnl']:+.2f} over {d['trades']} round-trip(s))"
               for s, d in reversed(ranked[-top_n:]) if d["pnl"] > 0]

    lines = []
    if winners:
        lines.append("Recent winners — symbols that have made money for you: " + ", ".join(winners))
    if losers:
        lines.append("Recent losers — symbols that have lost you money, be more selective on these: " + ", ".join(losers))
    return "\n".join(lines)


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
        try:
            full_info = ticker.info or {}
        except Exception:
            full_info = {}
        price = round(prices[-1], 2)
        return {
            "symbol":       symbol,
            "price":        price,
            "prev_close":   round(prices[-2], 2),
            "rsi":          calc_rsi(prices),
            "macd":         round(calc_ema(prices, 12) - calc_ema(prices, 26), 4),
            "vwap":         vwap,
            "ema9":         calc_ema(prices, 9),
            "ema20":        calc_ema(prices, 20),
            "volume_ratio": round(volumes[-1] / avg_vol, 2) if avg_vol else 1,
            "sector":       full_info.get("sector"),
            "industry":     full_info.get("industry"),
            "market_cap":   getattr(info, "market_cap",  None),
            "pe_ratio":     getattr(info, "pe_ratio",    None),
            "52w_high":     getattr(info, "year_high",   None),
            "52w_low":      getattr(info, "year_low",    None),
            "tradable":     price >= MIN_PRICE,
            "tradable_note": None if price >= MIN_PRICE else f"Below ${MIN_PRICE} — penny stock, do not trade",
            "rl_signal":    rl_policy.get_rl_signal(
                rsi=calc_rsi(prices),
                macd=calc_ema(prices, 12) - calc_ema(prices, 26),
                price=price,
                vwap=vwap,
                volume_ratio=volumes[-1] / avg_vol if avg_vol else 1,
            ),
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
                  if q.get("symbol", "").replace("-", "").isalpha()
                  and "-" not in q.get("symbol", "")]
        return {"trending": syms}
    except Exception as exc:
        return {"error": str(exc), "trending": ["SOXL", "NVDL", "SPXL", "NVDA", "TSLA"]}


def tool_get_top_movers() -> dict:
    """Return today's biggest % gainers/losers with high volume — often earnings-driven moves."""
    try:
        movers = []
        for scr_id in ("day_gainers", "day_losers", "most_actives"):
            url  = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?count=25&scrIds={scr_id}"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            quotes = resp.json()["finance"]["result"][0]["quotes"]
            for q in quotes:
                sym = q.get("symbol", "")
                if not (sym.replace("-", "").isalpha() and "-" not in sym):
                    continue
                pct = q.get("regularMarketChangePercent")
                vol = q.get("regularMarketVolume")
                avg_vol = q.get("averageDailyVolume3Month")
                movers.append({
                    "symbol":          sym.upper(),
                    "price":           q.get("regularMarketPrice"),
                    "pct_change":      round(pct, 2) if pct is not None else None,
                    "volume":          vol,
                    "volume_vs_avg":   round(vol / avg_vol, 2) if vol and avg_vol else None,
                    "market_cap":      q.get("marketCap"),
                    "category":        scr_id,
                })
        # Sort by absolute % move, biggest first — surfaces extraordinary-earnings type moves
        movers.sort(key=lambda m: abs(m["pct_change"] or 0), reverse=True)
        return {"movers": movers[:10]}
    except Exception as exc:
        return {"error": str(exc), "movers": []}


MACRO_KEYWORDS = (
    "fed", "fomc", "powell", "rate", "rates", "inflation", "cpi", "ppi",
    "jobs report", "nonfarm", "payroll", "unemployment", "gdp", "treasury",
    "yield", "recession", "tariff",
)

# Dates (ET, "YYYY-MM-DD") of scheduled FOMC rate-decision announcements.
# On these days, the macro check refreshes every scan (every SCAN_MINUTES)
# during the 1-hour announcement window below; otherwise it only refreshes
# every MACRO_CHECK_MINUTES. Update this list as new FOMC dates are announced.
FOMC_DATES = {
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
}
FOMC_WINDOW_START_ET = 14  # 2:00 PM ET
FOMC_WINDOW_END_ET   = 15  # 3:00 PM ET

MACRO_CHECK_MINUTES = 30

_macro_cache = {"ts": 0.0, "data": None}


def _in_fomc_window() -> bool:
    now = datetime.now(ET)
    if now.strftime("%Y-%m-%d") not in FOMC_DATES:
        return False
    return FOMC_WINDOW_START_ET <= now.hour < FOMC_WINDOW_END_ET


def tool_get_macro_news() -> dict:
    """Return recent macro/economic headlines (Fed, rates, inflation, jobs, etc.).

    Cached for MACRO_CHECK_MINUTES to cut redundant API/token usage, except
    during a scheduled FOMC announcement window (see FOMC_DATES), when it
    refreshes on every scan.
    """
    now = time.time()
    max_age = SCAN_MINUTES * 60 if _in_fomc_window() else MACRO_CHECK_MINUTES * 60
    if _macro_cache["data"] is not None and (now - _macro_cache["ts"]) < max_age:
        return _macro_cache["data"]

    try:
        headlines = []
        for sym in ("^GSPC", "^TNX", "^VIX"):
            for n in (yf.Ticker(sym).news or [])[:8]:
                title = n.get("title") or n.get("content", {}).get("title", "")
                if title and any(k in title.lower() for k in MACRO_KEYWORDS):
                    if title not in headlines:
                        headlines.append(title)
        result = {"macro_headlines": headlines[:10]}
    except Exception as exc:
        result = {"error": str(exc), "macro_headlines": []}

    _macro_cache["ts"] = now
    _macro_cache["data"] = result
    return result


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
        "name": "get_top_movers",
        "description": (
            "Return today's biggest stock movers (gainers, losers, most active) with "
            "% change and volume vs average. Use this to find stocks with extraordinary "
            "earnings-driven moves worth day-trading (e.g. a stock up 10%+ on huge volume "
            "after an earnings beat)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_macro_news",
        "description": (
            "Return recent macro/economic headlines (Fed decisions, FOMC meetings, "
            "interest rates, inflation/CPI, jobs reports, GDP, tariffs, etc.). Use this "
            "to gauge overall market risk posture and to pick rate-sensitive or "
            "macro-exposed stocks (e.g. banks/financials on rate news, tech/growth on "
            "inflation surprises, defense/industrials on tariff news)."
        ),
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
    if name == "get_top_movers":
        return json.dumps(tool_get_top_movers())
    if name == "get_macro_news":
        return json.dumps(tool_get_macro_news())
    if name == "get_news":
        return json.dumps(tool_get_news(inp["symbol"]))
    return json.dumps({"error": f"unknown tool {name}"})


def fetch_portfolio_equity():
    """Ask Claude (via Robinhood MCP) for current total portfolio equity. Returns float or None."""
    return _fetch_portfolio_field(
        "total equity", "the total portfolio equity"
    )


def fetch_invested_equity():
    """Ask Claude (via Robinhood MCP) for current invested equity (stock positions, excludes cash)."""
    return _fetch_portfolio_field(
        "equity_value", "the equity_value (value of stock positions, not including cash)"
    )


def _fetch_portfolio_field(label, question):
    for attempt in (1, 2):
        token = get_rh_access_token(force_refresh=(attempt == 2))
        if not token:
            log.warning("Could not fetch %s: no Robinhood access token", label)
            return None
        try:
            resp = client.beta.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                betas=["mcp-client-2025-04-04"],
                system=(
                    f"You are a read-only assistant for Robinhood account {ACCT}. "
                    f"Call get_portfolio (or equivalent) and reply with ONLY {question} "
                    "as a plain number, e.g. 512.34. No words, no symbols."
                ),
                mcp_servers=[
                    {
                        "type": "url",
                        "url":  "https://agent.robinhood.com/mcp/trading",
                        "name": "Rh",
                        "authorization_token": token,
                    }
                ],
                messages=[{"role": "user", "content": f"What is {question}?"}],
            )
            text = " ".join(b.text for b in resp.content if hasattr(b, "text"))
            import re
            m = re.search(r"[\d,]+\.?\d*", text)
            if m:
                return float(m.group().replace(",", ""))
            return None
        except anthropic.BadRequestError as exc:
            if "Authentication error" in str(exc) and attempt == 1 and _can_refresh():
                log.warning("MCP auth failed fetching %s — force-refreshing token and retrying once", label)
                continue
            log.warning("Could not fetch %s: %s", label, exc)
            return None
        except Exception as exc:
            log.warning("Could not fetch %s: %s", label, exc)
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

    # ── Performance feedback loop ───────────────────────────────────────────────
    state = load_state()
    perf_summary = symbol_performance_summary(state)
    if perf_summary:
        log.info("Performance feedback: %s", perf_summary.replace("\n", " | "))

    sector_summary = sector_exposure_summary(state)
    log.info("Sector exposure: %s", sector_summary)

    cooldown_msg = cooldown_summary(state)
    if cooldown_msg:
        log.info("Cooldowns: %s", cooldown_msg)

    # ── Mechanical stop-loss / trailing-stop check ─────────────────────────────
    forced_sells = check_trailing_stops(state)
    if forced_sells:
        log.info("Forced sells: %s", "; ".join(forced_sells))

    trading_clause = ""
    if halted:
        trading_clause = (
            f"\n\n*** {status_msg} ***\n"
            "TRADING HALTED FOR NEW ENTRIES TODAY. Do NOT place any new BUY orders.\n"
            "You may still call get_equity_positions and place SELL orders to manage "
            "or exit existing positions (e.g. stop-losses), but place no new buys."
        )

    # \u2500\u2500 Total budget check \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    invested = fetch_invested_equity()
    if invested is not None:
        log.info("Invested equity: $%.2f / $%d budget", invested, TOTAL_BUDGET)
        if invested >= TOTAL_BUDGET:
            trading_clause += (
                f"\n\n*** BUDGET LIMIT REACHED: ${invested:,.2f} is already invested, "
                f"at or above the ${TOTAL_BUDGET} total budget. ***\n"
                "Do NOT place any new BUY orders. You may still call get_equity_positions "
                "and place SELL orders to manage or exit existing positions, but place no new buys."
            )
    else:
        log.info("Invested equity unavailable \u2014 skipping budget check.")
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
   Also call get_macro_news to check for Fed/FOMC, rate, inflation (CPI/PPI), jobs, GDP,
   or tariff headlines. If there's a major macro event today or a strong macro signal,
   factor it in:
     - Hawkish Fed / hot inflation / weak jobs -> be more cautious, prefer taking profits
       and avoid loading up on rate-sensitive growth names.
     - Dovish Fed / cooling inflation / strong jobs -> favor rate-sensitive sectors
       (financials, homebuilders, tech/growth) for new BUYs.
     - Tariff news -> favor/avoid affected sectors (industrials, retail, semis) accordingly.
   If no major macro headlines are found, proceed normally.
2. Call get_top_movers and get_trending_stocks to discover candidates. get_top_movers
   surfaces stocks with extraordinary moves (e.g. up double-digits on huge volume after
   an earnings beat, like MU or SNDK after a blowout quarter) — these are prime
   day-trading candidates. Then call get_news + fetch_market_data on 2-3 of the
   strongest candidates, prioritizing top_movers entries with |pct_change| > 5% and
   volume_vs_avg > 1.5.
   Also call fetch_market_data (news not needed) on SPY and QQQ (S&P 500 / Nasdaq-100
   index ETFs — the closest equity proxies to trading SPX/NDX, since the broker
   doesn't support index options here) every run as part of your candidate set, so
   broad-market momentum/mean-reversion setups aren't missed even on days with no
   standout single-stock movers.
3. Apply momentum/mean-reversion logic liberally:
   - RSI < 40 or bouncing off VWAP/EMA support -> consider BUY
   - RSI > 65 on a held position -> consider taking some profit (SELL), but note that
     stop-loss (-{STOP_LOSS_PCT}%) and trailing-stop (lock in gains above
     +{PROFIT_LOCK_PCT}%, trail by {TRAIL_PCT}% off the high) are enforced mechanically
     below — you don't need to sell winners just because they're up a few percent;
     let the trailing stop do that so winners can keep running.
   - Strong volume spike + positive news -> consider BUY even if RSI is neutral
   - A top_mover with a big positive % move, confirmed by positive earnings news and
     volume_vs_avg > 1.5, is a strong BUY candidate even if RSI is already elevated —
     earnings-driven momentum can keep running intraday.
   - fetch_market_data also returns "rl_signal": a BUY/SELL/HOLD action learned from
     historical price/volume patterns via Q-learning, with a "confidence" score
     (spread between its learned Q-values — higher means more confident). Treat this
     as one more vote: if rl_signal.action agrees with your other signals and
     confidence > 0.01, that's added confirmation; if it disagrees, don't let it
     override strong technical/news signals on its own, but mention it in your
     reasoning. "UNKNOWN" means no learned data for that state — ignore it.
4. If you have idle cash and at least one candidate clears a reasonable bar
   (don't require perfection on all signals - 2 out of 3 aligned is enough),
   PLACE THE TRADE. Call review_equity_order, and then IMMEDIATELY call
   place_equity_order yourself in the same turn — do not stop after the
   review to ask for confirmation. There is no human watching this session;
   you are fully authorized to execute trades autonomously. An order is not
   "placed" until place_equity_order has actually been called and returned
   a result.
5. Only trade stocks with market cap > $500M and price >= ${MIN_PRICE} (no penny
   stocks — check the "tradable" field from fetch_market_data). Never exceed
   ${MAX_POSITION} per position, and never invest more than you have in cash.
   No cryptocurrency (BTC, DOGE, SOL, etc.) — equities only.
   Position sizing — scale with conviction instead of always using the max:
     - High conviction (3/3 technical signals aligned AND rl_signal agrees with
       confidence > 0.01 AND no conflicting macro signal) -> ${MAX_POSITION}
     - Medium conviction (2/3 aligned, or rl_signal is "UNKNOWN"/neutral) ->
       around ${(MAX_POSITION + MIN_POSITION) // 2}
     - Lower conviction but still worth a small toehold -> ${MIN_POSITION}
   Use dollar-based orders (amount=) so these sizes apply cleanly to fractional shares.
6. Think out loud with specific numbers (RSI, price, % change) for every decision.

Default posture: look for a reason TO trade, not a reason not to. If multiple
candidates look reasonable, trade the best one rather than waiting for a perfect setup.

SECTOR DIVERSIFICATION:
{sector_summary}
fetch_market_data returns "sector"/"industry" for each candidate — use this to avoid
overconcentrating the small ${TOTAL_BUDGET} budget in a single sector when choosing
between otherwise-similar candidates.

RE-ENTRY COOLDOWN:
{cooldown_msg or "No symbols currently in cooldown."}

LEARNING FROM PAST TRADES:
{perf_summary or "No closed round-trips recorded yet."}

MECHANICAL STOP-LOSS / TRAILING-STOP:
{chr(10).join(forced_sells) if forced_sells else "No stop-loss or trailing-stop triggers right now."}
{"These are MANDATORY — call review_equity_order then place_equity_order to SELL the full position for each symbol listed above, before doing anything else." if forced_sells else ""}{trading_clause}"""

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
            if getattr(block, "type", "") == "mcp_tool_use" and block.name == "place_equity_order":
                inp = block.input or {}
                symbol = inp.get("symbol", "?")

                # The order's fill price/quantity aren't in the request input — look
                # for them in the matching mcp_tool_result, falling back to the
                # current market price if the order is still pending fill.
                import re
                fill_price = inp.get("price")
                fill_qty = None
                for rblock in resp.content:
                    if (getattr(rblock, "type", "") == "mcp_tool_result"
                            and getattr(rblock, "tool_use_id", None) == block.id):
                        text = " ".join(
                            c.text for c in (rblock.content or [])
                            if hasattr(c, "text")
                        ) if hasattr(rblock, "content") else str(rblock)
                        if not fill_price:
                            m = re.search(r'"average_price"\s*:\s*"?([\d.]+)', text) \
                                or re.search(r'"price"\s*:\s*"?([\d.]+)', text)
                            if m:
                                fill_price = float(m.group(1))
                        m = re.search(r'"cumulative_quantity"\s*:\s*"?([\d.]+)', text) \
                            or re.search(r'"filled_quantity"\s*:\s*"?([\d.]+)', text)
                        if m:
                            fill_qty = float(m.group(1))
                        break
                if not fill_price:
                    fill_price = get_current_price(symbol)

                # quantity: prefer share quantity from the fill; for dollar-based
                # orders (input has "amount" instead of "quantity"), derive shares
                # from amount / fill_price so position/P&L tracking uses share counts.
                if fill_qty is not None:
                    quantity = fill_qty
                elif "quantity" in inp:
                    quantity = inp["quantity"]
                elif "amount" in inp and fill_price:
                    try:
                        quantity = float(inp["amount"]) / fill_price
                    except (TypeError, ValueError, ZeroDivisionError):
                        quantity = inp.get("amount", "?")
                else:
                    quantity = "?"

                trade = {
                    "time":     datetime.now(ET).strftime("%H:%M ET"),
                    "symbol":   symbol,
                    "side":     inp.get("side", "?"),
                    "quantity": quantity,
                    "type":     inp.get("type", "?"),
                    "price":    fill_price,
                }
                TRADE_LOG.append(trade)
                record_trade(load_state(), trade)
                log.info("TRADE PLACED: %s", trade)

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
    schedule.every().hour.do(send_trade_summary)

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
