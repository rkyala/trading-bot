"""
Rule-Based Trading Bot
Signals are computed deterministically in code (same math as backtest_v2.py).
Claude is used only to execute specific orders via the Robinhood MCP server.

Strategies (set STRATEGY below):
  momentum — buy when price > 30d VWAP, MACD > 0, volume >= 2x 10d avg;
             exit on a stop that starts -3% below entry and trails 5% below
             the highest price seen since entry.
  meanrev  — buy when RSI < 30 and price < 30d VWAP (truly oversold);
             exit at -3% stop or when RSI recovers above 50.

Safety rails:
  - Startup reconciliation: local positions.json is synced against actual
    Robinhood holdings, so cloud restarts can't orphan a position.
  - Auth-failure halt: if Robinhood auth fails, the bot stops trading and
    stays halted until ROBINHOOD_TOKEN is changed.
  - Daily loss limit: if the day's P&L drops below -DAILY_LOSS_LIMIT_PCT of
    budget, no new entries for the rest of the day (exits stay active).
  - Email notifications on fills, halts, and reconciliation changes
    (requires SMTP_HOST / SMTP_USER / SMTP_PASS env vars; logs otherwise).
"""

import anthropic
import requests
import yfinance as yf
import schedule
import time
import logging
import os
import sys
import json
import hashlib
import smtplib
from email.message import EmailMessage
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
MAX_POSITION = 125    # max $ per stock
TOTAL_BUDGET = 500

STRATEGY     = "momentum"   # "momentum" or "meanrev"
STOP_LOSS    = 0.03         # initial stop, fraction below entry
TRAIL_PCT    = 0.05         # momentum: trail this far below peak since entry
RSI_BUY      = 30           # meanrev entry threshold
RSI_EXIT     = 50           # meanrev exit threshold
VOL_RATIO    = 2.0          # momentum: volume vs 10d average

# Nasdaq-100 constituents as of 2026-06-10 — the universe validated in
# backtest_n100_results.json (momentum +54.6% / max DD -12.9% over 2y).
# Budget caps still limit the bot to 4 concurrent positions.
SYMBOLS = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "ALNY", "AMAT", "AMD",
    "AMGN", "AMZN", "APP", "ARM", "ASML", "AVGO", "AXON", "BKNG", "BKR", "CCEP",
    "CDNS", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSX", "CTAS",
    "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC", "FANG", "FAST", "FER", "FTNT",
    "GEHC", "GILD", "GOOG", "GOOGL", "HON", "IDXX", "INSM", "INTC", "INTU", "ISRG",
    "KDP", "KHC", "KLAC", "LIN", "LITE", "LRCX", "MAR", "MCHP", "MDLZ", "MELI",
    "META", "MNST", "MPWR", "MRVL", "MSFT", "MSTR", "MU", "NFLX", "NVDA", "NXPI",
    "ODFL", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PLTR", "PYPL", "QCOM",
    "REGN", "ROP", "ROST", "SBUX", "SHOP", "SNDK", "SNPS", "STX", "TMUS", "TRI",
    "TSLA", "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDAY", "WDC", "WMT", "XEL",
    "ZS",
]

DAILY_LOSS_LIMIT_PCT = 3.0  # halt new entries if day P&L < -3% of TOTAL_BUDGET

NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "kris.yalala@yahoo.com")
SMTP_HOST    = os.environ.get("SMTP_HOST", "")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")

# Persistent storage — point DATA_DIR at a mounted volume in cloud deploys so
# positions and rotated OAuth tokens survive restarts/redeploys.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = os.path.join(DATA_DIR, "positions.json")

# Pre-create yfinance's tz cache to avoid a mkdir race with threaded downloads
_yf_cache = os.path.join(DATA_DIR, "yf_cache")
os.makedirs(_yf_cache, exist_ok=True)
try:
    yf.set_tz_cache_location(_yf_cache)
except Exception:
    pass

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
TOKEN_FILE       = os.path.join(DATA_DIR, "rh_token.json")

if RH_CLIENT_ID and RH_REFRESH_TOKEN:
    log.info("Robinhood auth: OAuth refresh mode")
elif rh_token:
    log.warning("Robinhood auth: static ROBINHOOD_TOKEN (expires ~4 days) — "
                "run get_token.py and set RH_CLIENT_ID/RH_REFRESH_TOKEN instead.")
else:
    log.warning("No Robinhood credentials set — trades will fail auth.")

client = anthropic.Anthropic(api_key=api_key)


# ── Robinhood token management ────────────────────────────────────────────────

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

    # try the most recent refresh token first, then the env one
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


# ── Notifications ─────────────────────────────────────────────────────────────

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


def is_market_hours():
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    open_  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
    close_ = now.replace(hour=15, minute=45, second=0, microsecond=0)
    return open_ <= now <= close_


# ── Indicators (identical math to backtest_v2.py) ─────────────────────────────

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


def _indicators_from_df(df):
    if df is None or len(df) < 15:
        return None
    prices  = df["Close"].tolist()
    volumes = df["Volume"].tolist()
    n       = min(len(prices), len(volumes))
    vwap    = sum(prices[i] * volumes[i] for i in range(n)) / (sum(volumes[:n]) or 1)
    avg_vol = sum(volumes[-10:]) / 10
    return {
        "price":        prices[-1],
        "rsi":          calc_rsi(prices),
        "macd":         calc_ema(prices, 12) - calc_ema(prices, 26),
        "vwap":         round(vwap, 4),
        "volume_ratio": round(volumes[-1] / avg_vol, 2) if avg_vol else 1.0,
    }


def fetch_all_indicators(symbols):
    """One batched download for the whole universe -> {symbol: indicators}."""
    try:
        raw = yf.download(list(symbols), period="30d", interval="1d",
                          auto_adjust=True, progress=False,
                          group_by="ticker", threads=True)
    except Exception as exc:
        log.error("Batch market data download failed: %s", exc)
        return {}
    out = {}
    for sym in symbols:
        try:
            df = raw[sym].dropna()
        except (KeyError, IndexError):
            continue
        ind = _indicators_from_df(df)
        if ind:
            out[sym] = ind
    return out


# ── Signals ───────────────────────────────────────────────────────────────────

def entry_signal(ind):
    if STRATEGY == "momentum":
        return ind["price"] > ind["vwap"] and ind["macd"] > 0 and ind["volume_ratio"] >= VOL_RATIO
    return ind["rsi"] < RSI_BUY and ind["price"] < ind["vwap"]


def exit_signal(ind, pos):
    """Returns a reason string if the position should be closed, else None."""
    price = ind["price"]
    if STRATEGY == "momentum":
        stop = max(pos["entry"] * (1 - STOP_LOSS), pos["peak"] * (1 - TRAIL_PCT))
        if price <= stop:
            return f"trailing stop hit (price {price:.2f} <= stop {stop:.2f})"
    else:
        if price <= pos["entry"] * (1 - STOP_LOSS):
            return f"stop-loss hit (price {price:.2f}, entry {pos['entry']:.2f})"
        if ind["rsi"] > RSI_EXIT:
            return f"RSI recovered ({ind['rsi']:.1f} > {RSI_EXIT})"
    return None


# ── Position state ────────────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Halt handling ─────────────────────────────────────────────────────────────

def token_fp():
    """Fingerprint of user-supplied credentials — replacing any of them clears a halt."""
    material = rh_token + RH_CLIENT_ID + RH_REFRESH_TOKEN
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def set_halt(state, reason):
    state["halt"] = {
        "reason":   reason,
        "token_fp": token_fp(),
        "at":       datetime.now(ET).isoformat(),
    }
    save_state(state)
    notify("HALTED — trading stopped", f"Reason: {reason}\n\n"
           "The bot will not trade again until Robinhood credentials are replaced "
           "(new RH_REFRESH_TOKEN/RH_CLIENT_ID or ROBINHOOD_TOKEN clears the halt "
           "automatically).")


def is_halted(state):
    h = state.get("halt")
    if not h:
        return False
    if h.get("token_fp") != token_fp():
        log.info("Robinhood credentials changed — clearing halt (was: %s)", h.get("reason"))
        del state["halt"]
        save_state(state)
        return False
    return True


# ── Claude + Robinhood MCP ────────────────────────────────────────────────────

AUTH_INSTR = ('If any tool call fails with an authentication or authorization '
              'error (401/403, invalid/expired token), output exactly the line '
              'AUTH_ERROR and stop.')


def claude_call(system, user_msg):
    """One MCP conversation, with one token-refresh retry on auth failure.
    Returns (ok, combined_text)."""
    for attempt in (1, 2):
        token = get_rh_access_token(force_refresh=(attempt == 2))
        if not token:
            return False, "AUTH_ERROR: could not obtain a Robinhood access token"
        ok, text = _claude_call_once(system, user_msg, token)
        if "AUTH_ERROR" in text and attempt == 1 and _can_refresh():
            log.warning("MCP auth failed — force-refreshing token and retrying once")
            continue
        return ok, text
    return ok, text


def _claude_call_once(system, user_msg, token):
    messages = [{"role": "user", "content": user_msg}]
    texts = []
    try:
        for _ in range(8):
            resp = client.beta.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                betas=["mcp-client-2025-04-04"],
                system=system,
                mcp_servers=[{
                    "type": "url",
                    "url":  "https://agent.robinhood.com/mcp/trading",
                    "name": "Rh",
                    "authorization_token": token,
                }],
                messages=messages,
            )
            for block in resp.content:
                if hasattr(block, "text") and block.text:
                    texts.append(block.text)
                    log.info("executor: %s", block.text[:500])
            if resp.stop_reason in ("end_turn", "stop_sequence", "max_tokens"):
                return True, "\n".join(texts)
            # pause_turn / tool_use: continue the same conversation
            messages = messages + [
                {"role": "assistant", "content": resp.content},
                {"role": "user",      "content": "Continue."},
            ]
        log.warning("claude_call hit round limit")
        return False, "\n".join(texts)
    except Exception as exc:
        msg = str(exc)
        log.error("claude_call failed: %s", msg)
        # MCP auth failures surface as API-level 400s, not in-conversation text
        if "Authentication error while communicating with MCP server" in msg:
            return False, "AUTH_ERROR: " + msg
        return False, msg


def execute_order(side, symbol, dollars, reason):
    """Returns 'ok', 'auth', or 'fail'."""
    if side == "BUY":
        instruction = f"BUY ${dollars:.2f} (notional, market order) of {symbol}"
    else:
        instruction = f"SELL the ENTIRE position in {symbol} (market order)"

    system = f"""You are an order-execution agent for Robinhood account {ACCT}.
Execute EXACTLY this one order and nothing else:

    {instruction}

Reason for the order (for your log only): {reason}

Steps: call review_equity_order for this order, then place_equity_order to execute it.
Do not analyze the market, do not place any other order, do not skip execution.
{AUTH_INSTR}
After placing, output ORDER_PLACED on success, or "ORDER_FAILED: <error verbatim>" if rejected."""

    ok, text = claude_call(system, "Execute the order now.")
    if "AUTH_ERROR" in text:
        return "auth"
    if ok and "ORDER_PLACED" in text:
        return "ok"
    log.error("%s %s did not confirm: %s", side, symbol, text[-300:])
    return "fail"


def fetch_rh_positions():
    """Returns ('ok'|'auth'|'fail', [{'symbol','quantity','avg_price'}, ...])."""
    system = f"""You are a read-only assistant for Robinhood account {ACCT}.
Call get_equity_positions for this account. Then output ONLY a JSON array of the
open positions, no other text, in exactly this shape:
[{{"symbol": "ABC", "quantity": 1.23, "avg_price": 45.67}}]
Use an empty array [] if there are no positions. Do not place or modify any orders.
{AUTH_INSTR}"""

    ok, text = claude_call(system, "Fetch the positions now.")
    if "AUTH_ERROR" in text:
        return "auth", []
    if not ok:
        return "fail", []
    try:
        start, end = text.index("["), text.rindex("]") + 1
        raw = json.loads(text[start:end])
        out = []
        for p in raw:
            sym = str(p.get("symbol", "")).upper()
            qty = float(p.get("quantity", 0) or 0)
            avg = float(p.get("avg_price", 0) or 0)
            if sym and qty > 0 and avg > 0:
                out.append({"symbol": sym, "quantity": qty, "avg_price": avg})
        return "ok", out
    except (ValueError, TypeError) as exc:
        log.error("Could not parse positions from executor output: %s", exc)
        return "fail", []


# ── Startup reconciliation ────────────────────────────────────────────────────

def reconcile(state):
    log.info("Reconciling local state against Robinhood positions...")
    status, rh_positions = fetch_rh_positions()

    if status == "auth":
        set_halt(state, "Robinhood auth failed during startup reconciliation")
        return
    if status == "fail":
        notify("Reconciliation failed",
               "Could not fetch Robinhood positions at startup. "
               "Continuing with local positions.json state — verify manually.")
        return

    positions = state.setdefault("positions", {})
    rh_by_sym = {p["symbol"]: p for p in rh_positions}
    changes   = []

    for sym in list(positions):
        if sym not in rh_by_sym:
            changes.append(f"DROPPED {sym}: tracked locally but not held in Robinhood "
                           "(closed externally?)")
            del positions[sym]

    for sym, p in rh_by_sym.items():
        if sym in positions:
            continue
        if sym not in SYMBOLS:
            log.info("Ignoring %s held in account — not in bot universe", sym)
            continue
        positions[sym] = {
            "entry":      p["avg_price"],
            "peak":       p["avg_price"],
            "dollars":    round(p["quantity"] * p["avg_price"], 2),
            "entry_date": "adopted " + datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        }
        changes.append(f"ADOPTED {sym}: {p['quantity']} sh @ ${p['avg_price']:.2f} "
                       f"(${positions[sym]['dollars']:.2f}) — stop set from avg cost")

    save_state(state)
    if changes:
        notify("Startup reconciliation: state changed", "\n".join(changes))
        for c in changes:
            log.info("reconcile: %s", c)
    else:
        log.info("Reconciliation clean — local state matches Robinhood (%d position(s))",
                 len(positions))


# ── Daily loss limit ──────────────────────────────────────────────────────────

def roll_daily(state):
    today = datetime.now(ET).strftime("%Y-%m-%d")
    d = state.get("daily")
    if not d or d.get("date") != today:
        state["daily"] = {"date": today, "realized": 0.0, "halted": False}
    return state["daily"]


def mark_day(pos, price, today):
    """First price seen today becomes the position's day-start mark."""
    if pos.get("day_mark_date") != today:
        pos["day_mark"]      = price
        pos["day_mark_date"] = today


def daily_pnl(state, positions):
    d = state["daily"]
    unrealized = 0.0
    for pos in positions.values():
        last = pos.get("last_price")
        mark = pos.get("day_mark")
        if last and mark:
            unrealized += pos["dollars"] / pos["entry"] * (last - mark)
    return d["realized"] + unrealized


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_trading_loop():
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return

    now   = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    state = load_state()

    if is_halted(state):
        log.warning("Bot is HALTED (%s) — no trading. Replace ROBINHOOD_TOKEN to resume.",
                    state["halt"]["reason"])
        return

    log.info("═══ %s scan at %s ═══", STRATEGY, now)
    positions = state.setdefault("positions", {})
    daily     = roll_daily(state)
    today     = daily["date"]
    loss_limit = TOTAL_BUDGET * DAILY_LOSS_LIMIT_PCT / 100

    market = fetch_all_indicators(sorted(set(SYMBOLS) | set(positions)))
    if not market:
        log.warning("No market data this scan — skipping")
        return

    # 1. manage open positions
    for symbol in list(positions):
        ind = market.get(symbol)
        if ind is None:
            continue
        pos = positions[symbol]
        mark_day(pos, ind["price"], today)
        pos["peak"]       = max(pos.get("peak", pos["entry"]), ind["price"])
        pos["last_price"] = ind["price"]
        reason = exit_signal(ind, pos)
        if reason:
            log.info("%s SELL signal: %s", symbol, reason)
            status = execute_order("SELL", symbol, None, reason)
            if status == "auth":
                set_halt(state, f"Robinhood auth failed selling {symbol}")
                return
            if status == "ok":
                pnl = pos["dollars"] / pos["entry"] * (ind["price"] - pos["day_mark"])
                daily["realized"] += pnl
                est_total = pos["dollars"] * (ind["price"] / pos["entry"] - 1)
                notify(f"SELL {symbol} — {reason}",
                       f"Sold entire {symbol} position.\nEntry ${pos['entry']:.2f}, "
                       f"exit ~${ind['price']:.2f}, est. P&L ${est_total:+.2f}.")
                del positions[symbol]
            else:
                notify(f"SELL {symbol} FAILED",
                       f"Exit signal fired ({reason}) but the order did not confirm. "
                       "Check the account manually.")
        else:
            log.info("%s HOLD  price=%.2f entry=%.2f peak=%.2f rsi=%.1f",
                     symbol, ind["price"], pos["entry"], pos["peak"], ind["rsi"])

    # 2. daily loss limit — blocks new entries, never exits
    pnl_today = daily_pnl(state, positions)
    if not daily["halted"] and pnl_today <= -loss_limit:
        daily["halted"] = True
        notify("Daily loss limit hit — no new entries today",
               f"Day P&L ${pnl_today:+.2f} breached -${loss_limit:.2f} "
               f"({DAILY_LOSS_LIMIT_PCT}% of ${TOTAL_BUDGET}). "
               "Open positions keep their stops; entries resume tomorrow.")

    # 3. look for entries within budget
    budget_used = sum(p["dollars"] for p in positions.values())
    if daily["halted"]:
        log.info("Entries blocked for today (daily loss limit). Day P&L: $%+.2f", pnl_today)
    else:
        scanned = 0
        for symbol in SYMBOLS:
            if symbol in positions:
                continue
            available = TOTAL_BUDGET - budget_used
            if available < 1:
                break
            ind = market.get(symbol)
            if ind is None:
                continue
            scanned += 1
            if entry_signal(ind):
                dollars = min(MAX_POSITION, available)
                detail  = (f"price={ind['price']:.2f} vwap={ind['vwap']:.2f} "
                           f"macd={ind['macd']:.3f} rsi={ind['rsi']:.1f} "
                           f"vol={ind['volume_ratio']:.1f}x")
                log.info("%s BUY signal (%s): %s", symbol, STRATEGY, detail)
                status = execute_order("BUY", symbol, dollars, f"{STRATEGY} entry: {detail}")
                if status == "auth":
                    set_halt(state, f"Robinhood auth failed buying {symbol}")
                    return
                if status == "ok":
                    positions[symbol] = {
                        "entry":         ind["price"],
                        "peak":          ind["price"],
                        "dollars":       dollars,
                        "entry_date":    now,
                        "day_mark":      ind["price"],
                        "day_mark_date": today,
                        "last_price":    ind["price"],
                    }
                    budget_used += dollars
                    notify(f"BUY {symbol} ${dollars:.0f}",
                           f"{STRATEGY} entry at ~${ind['price']:.2f}\n{detail}")
                else:
                    notify(f"BUY {symbol} FAILED",
                           f"Entry signal fired but the order did not confirm.\n{detail}")
        log.info("Scanned %d symbols for entries", scanned)

    save_state(state)
    log.info("Scan complete — %d open, $%.0f/$%d budget, day P&L $%+.2f",
             len(positions), budget_used, TOTAL_BUDGET, daily_pnl(state, positions))


def main():
    log.info("Rule-based trading bot starting — strategy=%s", STRATEGY)
    log.info("Scan: %d min | Account: %s | Budget: $%d | Max/position: $%d | "
             "Daily loss limit: %.1f%% | Notify: %s",
             SCAN_MINUTES, ACCT, TOTAL_BUDGET, MAX_POSITION,
             DAILY_LOSS_LIMIT_PCT, NOTIFY_EMAIL)

    state = load_state()
    if not is_halted(state):
        reconcile(state)
        notify("Bot started",
               f"Strategy: {STRATEGY} | Universe: {len(SYMBOLS)} symbols | "
               f"Budget: ${TOTAL_BUDGET} | Open positions: "
               f"{len(state.get('positions', {}))}\n"
               "If you received this, email notifications are working.")
    else:
        log.warning("Starting HALTED (%s) — replace Robinhood credentials to resume.",
                    state["halt"]["reason"])

    schedule.every(SCAN_MINUTES).minutes.do(run_trading_loop)

    log.info("Running first scan immediately...")
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
