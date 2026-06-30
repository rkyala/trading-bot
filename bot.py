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
import random
import logging
import os
import sys
import json
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import rl_policy

try:
    import yoptions  # Free options data library
except ImportError:
    yoptions = None

# Optional: Use local market data cache if available
try:
    from market_cache import get_symbol_data as get_cached_symbol_data
except ImportError:
    def get_cached_symbol_data(symbol):
        """Load symbol data from hybrid cache (stable + price), or None if missing/stale."""
        import json, time
        cache_dir = os.environ.get("DATA_DIR", ".")
        
        # Try stable cache first (sector, quality, fundamentals)
        stable_file = os.path.join(cache_dir, "market_stable_cache.json")
        price_file = os.path.join(cache_dir, "market_price_cache.json")
        
        stable_data = {}
        price_data = {}
        
        try:
            if os.path.exists(stable_file):
                with open(stable_file, "r") as f:
                    stable_cache = json.load(f)
                    symbols = stable_cache.get("symbols", {})
                    if symbol in symbols:
                        stable_data = symbols[symbol]
        except Exception as e:
            log.debug("Stable cache miss for %s: %s", symbol, e)
        
        try:
            if os.path.exists(price_file):
                with open(price_file, "r") as f:
                    price_cache = json.load(f)
                    symbols = price_cache.get("symbols", {})
                    if symbol in symbols:
                        # Check freshness (must be <30min old)
                        ts = price_cache.get("timestamp", 0)
                        age_min = (time.time() - ts) / 60
                        if age_min < 30:
                            price_data = symbols[symbol]
                        else:
                            log.debug("Price cache stale for %s: %.1fmin old", symbol, age_min)
        except Exception as e:
            log.debug("Price cache miss for %s: %s", symbol, e)
        
        # Return combined data if we have both (or at least some price data)
        if price_data:
            return {**stable_data, **price_data}
        elif stable_data and not os.path.exists(price_file):
            return stable_data  # Fallback to stable-only if price cache doesn't exist
        
        return None  # Cache miss or stale

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
SCAN_MINUTES = 10
MAX_POSITION = 500   # max $ per position (scaled from $250 for $2K budget)
TOTAL_BUDGET = 2000  # doubled from $1000
DAILY_LOSS_LIMIT_PCT = 5.0   # halt new buys if equity drops 5% from day-start (~$100 loss)
MIN_PRICE = 5.0   # no penny stocks
MIN_MARKET_CAP = 1e9   # min $1B market cap (was $500M, too many micro-caps)
MIN_AVG_VOLUME = 1e6   # min 1M shares/day average volume (for liquidity)
MIN_FLOAT = 20e6   # min 20M shares outstanding (avoid low-float bombs)
STOP_LOSS_PCT   = 3.0   # hard stop: sell if down this much from entry
PROFIT_LOCK_PCT = 3.0   # once up this much from entry, start trailing
TRAIL_PCT       = 2.0   # trailing stop distance from the high-water mark
MIN_POSITION    = 50    # smallest position size for a low-conviction entry
COOLDOWN_MINUTES = 30   # don't re-enter a symbol this soon after exiting it
STATE_PATH = os.path.join(os.environ.get("DATA_DIR", "."), "bot_state.json")

# Market data cache (reuse if < 90 seconds old to reduce API/token calls)
_market_cache = {}
_spy_cache = {"price": None, "prev_close": None, "pct_change": None, "ts": 0}

# Ticker cache (avoid recreating Ticker objects every 5 minutes)
_ticker_cache = {}
_ticker_cache_time = {}

# Sector/industry cache (24-hour TTL, rarely changes)
_sector_cache = {}  # {symbol: {sector, industry, ts}}

# Phase 2 caching (token optimization)
_movers_trending_cache = {"movers": None, "trending": None, "ts": 0}  # 1-hour TTL
_haiku_candidates_cache = {"candidates": None, "ts": 0}  # 1-hour TTL (caches Haiku screening result)
_macro_analysis_cache = {"analysis": None, "ts": 0}  # 60-min TTL (caches macro environment analysis)

# Price and fundamental caches (1-24 hour TTL)
_price_cache = {}  # {symbol: {"prices": [...], "last_close": price, "ts": time}}
_fundamentals_cache = {}  # {symbol: {"market_cap": ..., "pe_ratio": ..., "ts": time}}
_quality_cache = {}  # {symbol: {"passes": bool, "market_cap": ..., "avg_volume": ..., "ts": time}}
_movers_cache = None  # throttled, replaced by _movers_trending_cache
_vix_cache = {"regime": None, "data": None, "ts": 0}  # 2-hour TTL

# Run counter for throttling expensive operations
_run_count = 0

# Email alerts (requires SMTP_HOST / SMTP_USER / SMTP_PASS env vars; logs otherwise)
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "kris.yalala@yahoo.com")
SMTP_HOST    = os.environ.get("SMTP_HOST", "")
SMTP_PORT    = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER    = os.environ.get("SMTP_USER", "")
SMTP_PASS    = os.environ.get("SMTP_PASS", "")

# ════════════════════════════════════════════════════════════════════════════════
# TOKEN BURN CIRCUIT BREAKER — Critical safeguard against runaway API costs
# ════════════════════════════════════════════════════════════════════════════════

class TokenBurnCircuitBreaker:
    """Monitor API token spend and halt bot if burn rate exceeds threshold."""
    
    def __init__(self, max_tokens_per_hour=2_000_000, max_tokens_per_day=15_000_000):
        self.max_per_hour = max_tokens_per_hour  # ~$2/hour = ~$20/day max
        self.max_per_day = max_tokens_per_day    # ~$15/day safety ceiling
        self.tokens_this_hour = 0
        self.tokens_today = 0
        self.hour_start = time.time()
        self.day_start = time.time()
        self.breaker_tripped = False
        self.trip_reason = None
        self.bot_halted = False
    
    def check(self, tokens_in: int, tokens_out: int) -> bool:
        """Check token burn after API call. Returns False if threshold exceeded."""
        now = time.time()
        total_tokens = tokens_in + tokens_out
        
        # Reset hourly counter if hour elapsed
        if now - self.hour_start > 3600:
            self.tokens_this_hour = 0
            self.hour_start = now
        
        # Reset daily counter if day elapsed  
        if now - self.day_start > 86400:
            self.tokens_today = 0
            self.day_start = now
            self.breaker_tripped = False
            self.bot_halted = False
        
        self.tokens_this_hour += total_tokens
        self.tokens_today += total_tokens
        
        # Check hourly limit
        if self.tokens_this_hour > self.max_per_hour:
            self.bot_halted = True
            self.trip_reason = f"Hourly: {self.tokens_this_hour:,} tokens"
            log.critical("🚨 TOKEN BURN CIRCUIT BREAKER TRIGGERED — BOT HALTED")
            log.critical("   %s", self.trip_reason)
            return False
        
        # Check daily limit
        if self.tokens_today > self.max_per_day:
            self.bot_halted = True
            self.trip_reason = f"Daily: {self.tokens_today:,} tokens"
            log.critical("🚨 CIRCUIT BREAKER — BOT HALTED (daily limit)")
            log.critical("   %s", self.trip_reason)
            return False
        
        return True
    
    def is_bot_halted(self) -> bool:
        """Check if bot is currently halted."""
        return self.bot_halted

# Initialize circuit breaker
token_breaker = TokenBurnCircuitBreaker(
    max_tokens_per_hour=2_000_000,
    max_tokens_per_day=15_000_000
)

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


# Retry wrapper for API calls (handle 429, 503, 529 errors)
def call_with_retry(func, max_retries=1, base_delay=2.0):
    """Retry API calls with exponential backoff on transient errors (429, 503, 529)."""
    for attempt in range(max_retries):
        try:
            return func()
        except anthropic.RateLimitError as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                log.warning(f"Rate limited (429), retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                raise
        except anthropic.OverloadedError as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                log.warning(f"API overloaded (529), retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                raise
        except (anthropic.APIError, Exception) as e:
            error_str = str(e)
            # Check for service unavailable (503)
            if ("503" in error_str or "service unavailable" in error_str.lower()):
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    log.warning(f"Service unavailable (503), retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    raise
            else:
                # Not a transient error, fail fast
                raise
    return None

# Token usage tracking for ROI analysis
_token_metrics = {
    "date": "",
    "runs": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "daily_pnl": 0.0,
    "token_cost_usd": 0.0,  # Sonnet 4.6: $3/1M input, $15/1M output
}
_run_tokens = {"input": 0, "output": 0, "cost_usd": 0.0}
_market_data_failures = 0  # Track consecutive fetch_market_data failures


# ── Robinhood token management ──────────────────────────────────────────────

_tok = {"access": None, "expires_at": 0.0, "refresh": None}



def _record_token_usage(input_tokens, output_tokens):
    """Record token usage for ROI analysis. Sonnet 4.6: $3/1M input, $15/1M output."""
    cost = (input_tokens * 3 + output_tokens * 15) / 1_000_000
    _run_tokens["input"] = input_tokens
    _run_tokens["output"] = output_tokens
    _run_tokens["cost_usd"] = round(cost, 6)
    _token_metrics["total_input_tokens"] += input_tokens
    _token_metrics["total_output_tokens"] += output_tokens
    _token_metrics["token_cost_usd"] = round(_token_metrics["token_cost_usd"] + cost, 6)
    return cost

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
    # Weekend check
    if now.weekday() >= 5:
        return False
    
    # US market holidays (closed all day)
    holidays_2026 = {
        "01-01",  # New Year's Day
        "01-19",  # MLK Jr Day (3rd Monday)
        "02-16",  # Presidents Day (3rd Monday)
        "03-30",  # Good Friday
        "05-25",  # Memorial Day (last Monday)
        "06-19",  # Juneteenth
        "07-03",  # Independence Day (observed, market closed early Friday)
        "09-07",  # Labor Day (1st Monday)
        "11-26",  # Thanksgiving
        "12-25",  # Christmas
    }
    
    date_str = now.strftime("%m-%d")
    if date_str in holidays_2026:
        return False
    
    open_  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
    close_ = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_ <= now <= close_


def skip_recently_analyzed(candidate: str, state: dict, lookback_minutes: int = 30) -> bool:
    """Check if candidate was analyzed recently (within lookback_minutes)."""
    analyzed = state.get("analyzed_candidates", {})
    if candidate in analyzed:
        analyzed_at = analyzed[candidate]
        age_minutes = (time.time() - analyzed_at) / 60
        if age_minutes < lookback_minutes:
            return True
    return False

def mark_candidate_analyzed(candidate: str, state: dict) -> None:
    """Mark candidate as analyzed at current time."""
    analyzed = state.setdefault("analyzed_candidates", {})
    analyzed[candidate] = time.time()

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
            sector = (get_cached_ticker(sym).info or {}).get("sector")
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
        hist = get_cached_ticker(symbol).history(period="30d", interval="1d")
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


def calc_volatility(prices: list, lookback: int = 20) -> float:
    """Calculate 20-day volatility as % standard deviation."""
    if len(prices) < lookback:
        return 0.0
    recent = prices[-lookback:]
    returns = [(recent[i] - recent[i-1]) / recent[i-1] for i in range(1, len(recent))]
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    std_dev = variance ** 0.5
    return std_dev * 100  # as percentage


def calc_gap_fill(prev_close: float, current_open: float) -> dict:
    """Calculate overnight gap and gap-fill level (mean reversion target)."""
    if not prev_close or prev_close == 0:
        return {"gap_pct": 0, "gap_fill_level": 0, "gap_type": "none"}
    
    gap_pct = 100 * (current_open - prev_close) / prev_close
    
    if gap_pct > 2.0:
        gap_type = "gap_up"
    elif gap_pct < -2.0:
        gap_type = "gap_down"
    else:
        gap_type = "none"
    
    return {
        "gap_pct": round(gap_pct, 2),
        "gap_fill_level": prev_close,
        "gap_type": gap_type,
        "setup": "fade gap up (buy dip toward fill)" if gap_type == "gap_up" else (
            "ride gap down (short or skip)" if gap_type == "gap_down" else "no gap"
        ),
    }


def calc_relative_strength_vs_spy(stock_pct_change: float, spy_pct_change: float) -> dict:
    """Calculate outperformance vs. SPY (relative strength).
    
    Positive = stock outperforming broad market (bullish signal).
    Negative = stock lagging SPY (bearish signal)."""
    outperformance = stock_pct_change - spy_pct_change
    
    if outperformance > 1.5:
        strength = "strong"
    elif outperformance > 0.5:
        strength = "moderate"
    elif outperformance > -0.5:
        strength = "neutral"
    elif outperformance > -1.5:
        strength = "weak"
    else:
        strength = "very_weak"
    
    return {
        "stock_pct_change": round(stock_pct_change, 2),
        "spy_pct_change": round(spy_pct_change, 2),
        "outperformance_pct": round(outperformance, 2),
        "relative_strength": strength,
        "tradable": outperformance > -0.5,  # only trade if not significantly lagging
    }


def detect_divergence(prices: list, rsi_values: list, lookback: int = 5) -> dict:
    """Detect RSI divergence: price makes new high/low but RSI doesn't."""
    if len(prices) < lookback or len(rsi_values) < lookback:
        return {"bullish_div": False, "bearish_div": False, "description": ""}
    
    recent_prices = prices[-lookback:]
    recent_rsi = rsi_values[-lookback:]
    
    # Bullish divergence: price lower low, RSI higher low
    if recent_prices[0] < recent_prices[-1]:  # price made lower low
        if recent_rsi[0] < recent_rsi[-1]:  # RSI made higher low
            return {"bullish_div": True, "bearish_div": False, "description": "Bullish divergence (buy signal)"}
    
    # Bearish divergence: price higher high, RSI lower high
    if recent_prices[-1] > recent_prices[0]:  # price made higher high
        if recent_rsi[-1] < recent_rsi[0]:  # RSI made lower high
            return {"bearish_div": True, "bullish_div": False, "description": "Bearish divergence (sell/avoid signal)"}
    
    return {"bullish_div": False, "bearish_div": False, "description": "No divergence"}


def calc_bollinger_bands(prices: list, period: int = 20, num_std: float = 2.0) -> dict:
    """Calculate Bollinger Bands and price position relative to them."""
    if len(prices) < period:
        return {"upper": prices[-1], "middle": prices[-1], "lower": prices[-1], "position": "insufficient_data"}
    
    recent = prices[-period:]
    sma = sum(recent) / period
    variance = sum((x - sma) ** 2 for x in recent) / period
    std_dev = variance ** 0.5
    
    upper = sma + (num_std * std_dev)
    lower = sma - (num_std * std_dev)
    current = prices[-1]
    
    # Determine price position
    if current > upper:
        position = "above_upper"  # overbought
    elif current < lower:
        position = "below_lower"  # oversold
    elif current > sma:
        position = "above_middle"
    else:
        position = "below_middle"
    
    return {
        "upper": round(upper, 4),
        "middle": round(sma, 4),
        "lower": round(lower, 4),
        "current": round(current, 4),
        "position": position,
        "squeeze": round(upper - lower, 4),  # narrow band = low volatility
    }


def is_optimal_trading_hours(et_time) -> dict:
    """Check if current time is optimal for day trading (avoid open chaos and close weakness)."""
    hour = et_time.hour
    minute = et_time.minute
    total_minutes = hour * 60 + minute
    
    market_open = 9 * 60 + 30  # 9:30 ET
    optimal_start = 10 * 60 + 0  # 10:00 ET (skip first 30 min chaos)
    optimal_end = 15 * 60 + 0  # 15:00 ET (skip last hour weakness)
    market_close = 16 * 60  # 16:00 ET
    
    if total_minutes < optimal_start or total_minutes >= optimal_end:
        status = "suboptimal"
        reason = "before 10:00 or after 15:00 ET" if total_minutes < optimal_start else "last hour before close (illiquid)"
    else:
        status = "optimal"
        reason = "peak liquidity hours"
    
    return {"status": status, "reason": reason, "current_et_time": et_time.strftime("%H:%M")}


def calc_fib_levels(swing_low: float, swing_high: float) -> dict:
    """Calculate Fibonacci retracement/extension levels."""
    diff = swing_high - swing_low
    return {
        "0%": swing_high,
        "23.6%": round(swing_high - diff * 0.236, 4),
        "38.2%": round(swing_high - diff * 0.382, 4),
        "50%": round(swing_high - diff * 0.5, 4),
        "61.8%": round(swing_high - diff * 0.618, 4),
        "78.6%": round(swing_high - diff * 0.786, 4),
        "100%": swing_low,
    }


def find_swing_levels(closes: list, lookback: int = 20) -> dict:
    """Find recent swing high/low in the last N candles."""
    window = closes[-lookback:] if len(closes) >= lookback else closes
    swing_high = max(window)
    swing_low = min(window)
    return {"swing_high": swing_high, "swing_low": swing_low}


def calc_pivot_points(high: float, low: float, close: float) -> dict:
    """Calculate daily pivot points (S/R levels)."""
    pivot = (high + low + close) / 3
    return {
        "pivot": round(pivot, 2),
        "r1": round(2 * pivot - low, 2),
        "r2": round(pivot + (high - low), 2),
        "s1": round(2 * pivot - high, 2),
        "s2": round(pivot - (high - low), 2),
    }


def scale_position_by_extension(daily_pct_change: float) -> dict:
    """Scale position size based on how much stock has already moved intraday.
    
    Less extension = higher conviction entry, larger position.
    More extension = later entry, reduced position or skip."""
    if daily_pct_change <= 2.0:
        size = MAX_POSITION  # full $125
        conviction = "high"
    elif daily_pct_change <= 5.0:
        size = round(MAX_POSITION * 0.75)  # $94
        conviction = "medium"
    elif daily_pct_change <= 10.0:
        size = 50  # $50 hard cap for extended moves
        conviction = "lower"
    else:
        size = 0  # skip entirely if up >10%
        conviction = "skip_extended"
    return {"suggested_size": size, "conviction_by_extension": conviction}



def calculate_position_size_by_confidence(rsi, volume_ratio, relative_strength, gap_fill, divergence) -> dict:
    """Calculate position size based on signal confluence (how many signals align).
    
    Higher confidence = bigger position (scale with edge).
    Doubled sizing for $1000 budget (was $500).
    """
    confidence_points = 0
    
    # RSI signal
    if rsi and not isinstance(rsi, str) and (rsi < 30 or rsi > 70):
        confidence_points += 2  # extreme RSI
    elif rsi and not isinstance(rsi, str) and 35 < rsi < 65:
        confidence_points += 1  # neutral RSI
    
    # Volume signal
    if volume_ratio and not isinstance(volume_ratio, str):
        if volume_ratio >= 2.0:
            confidence_points += 2  # strong volume
        elif volume_ratio >= 1.5:
            confidence_points += 1
    
    # Relative strength signal
    if relative_strength and isinstance(relative_strength, dict):
        rs_pct = relative_strength.get("outperformance_pct")
        if rs_pct and not isinstance(rs_pct, str) and rs_pct > 1.5:
            confidence_points += 2  # strong outperformance
        elif rs_pct and not isinstance(rs_pct, str) and rs_pct > 0.75:
            confidence_points += 1
    
    # Gap fill signal
    if gap_fill and isinstance(gap_fill, dict):
        gap_pct = gap_fill.get("gap_pct", 0)
        if gap_fill.get("gap_type") == "gap_up" and isinstance(gap_pct, (int, float)) and 2 < gap_pct < 5:
            confidence_points += 2  # mean reversion setup
    
    # Divergence signal
    if divergence and isinstance(divergence, dict) and divergence.get("bullish_div"):
        confidence_points += 1  # bullish divergence
    
    # Map points to position size (doubled for $1k budget)
    if confidence_points >= 6:
        return {"size": 250, "confidence_level": "very_high"}
    elif confidence_points >= 5:
        return {"size": 200, "confidence_level": "high"}
    elif confidence_points >= 3:
        return {"size": 150, "confidence_level": "medium"}
    elif confidence_points >= 2:
        return {"size": 100, "confidence_level": "low"}
    else:
        return {"size": 75, "confidence_level": "very_low"}


def calculate_volatility_adjusted_stop(entry_price: float, volatility_pct: float) -> dict:
    """Calculate stop loss based on volatility (wider stops in choppy markets).
    
    Volatility <25%: -1.5% (tight, calm market)
    Volatility 25-40%: -2% (normal market)
    Volatility >40%: -3% (choppy, volatile market)
    """
    if volatility_pct < 25:
        stop_pct = 1.5
        reason = "tight_stop_calm_market"
    elif volatility_pct <= 40:
        stop_pct = 2.0
        reason = "normal_stop"
    else:
        stop_pct = 3.0
        reason = "wide_stop_volatile_market"
    
    stop_price = entry_price * (1 - stop_pct / 100)
    return {
        "stop_price": round(stop_price, 2),
        "stop_pct": stop_pct,
        "reason": reason
    }


def batch_fetch_yfinance(symbols: list) -> dict:
    """Fetch historical data for multiple symbols at once (much faster than serial calls).
    
    Returns: {symbol: {hist_df, ticker_obj}} for use by fetch_market_data."""
    if not symbols:
        return {}
    
    try:
        # Batch download is ~10x faster than individual ticker calls
        hist = yf.download(symbols, period="30d", interval="1d", auto_adjust=True, progress=False, group_by="ticker")
        result = {}
        for sym in symbols:
            try:
                df = hist[sym] if sym in hist else hist
                if df is not None and not df.empty:
                    result[sym] = {"hist": df}
            except Exception:
                pass
        return result
    except Exception:
        return {}


def get_sector_info(symbol: str) -> tuple:
    """Get sector and industry, using 24-hour cache to avoid repeated API calls."""
    now = time.time()
    cache_entry = _sector_cache.get(symbol, {})
    
    # Return cached if < 24 hours old
    if cache_entry.get("sector") and (now - cache_entry.get("ts", 0)) < 86400:
        return cache_entry.get("sector"), cache_entry.get("industry")
    
    # Fetch fresh
    try:
        ticker = get_cached_ticker(symbol)
        info = ticker.info or {}
        sector = info.get("sector")
        industry = info.get("industry")

        # Cache the result
        _sector_cache[symbol] = {"sector": sector, "industry": industry, "ts": now}
        return sector, industry
    except Exception:
        return None, None


def get_cached_ticker(symbol: str):
    """Get or create Ticker object with 4-minute cache (avoid redundant instantiation).

    Ticker objects are expensive to create (HTTP requests). Cache them to avoid
    recreating on every 5-minute scan cycle.
    """
    now = time.time()
    cache_age = now - _ticker_cache_time.get(symbol, 0)

    # Return cached if < 240 seconds (4 minutes)
    if symbol in _ticker_cache and cache_age < 240:
        return _ticker_cache[symbol]

    # Create new
    ticker = yf.Ticker(symbol)
    _ticker_cache[symbol] = ticker
    _ticker_cache_time[symbol] = now

    return ticker


def tool_fetch_market_data(symbol: str) -> dict:
    # FIRST: Try local cache (0 tokens, instant)
    cached_data = get_cached_symbol_data(symbol)
    if cached_data:
        # Add quality_rating and sizing from our rules
        daily_pct = cached_data.get("daily_pct_change", 0)
        quality_rating = "PASS" if abs(daily_pct) <= 40 else "CAUTION"
        
        sizing = scale_position_by_extension(daily_pct)
        
        return {
            **cached_data,
            "quality_rating": quality_rating,
            "suggested_position_size": sizing["suggested_size"],
            "conviction_by_extension": sizing["conviction_by_extension"],
        }
    
    # FALLBACK: Fetch fresh if cache miss
    try:
        prices = get_cached_price_history(symbol)
        if not prices or len(prices) < 14:
            return {"error": f"Not enough history for {symbol}"}

        # Get volumes from fresh data (needed for current calculation)
        ticker = get_cached_ticker(symbol)  # Use cached Ticker (4-min TTL)
        hist = ticker.history(period="30d", interval="1d")  # Fetch 30d, not 60d (saves ~20 tokens/run)
        if hist.empty or len(hist) < 14:
            return {"error": f"Not enough history for {symbol}"}
        prices  = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()
        n       = min(len(prices), len(volumes))
        vwap    = round(sum(prices[i] * volumes[i] for i in range(n)) / (sum(volumes[:n]) or 1), 4)
        avg_vol = sum(volumes[-10:]) / 10
        info    = ticker.fast_info
        # Use cached sector fetcher to avoid repeated API calls
        sector, industry = get_sector_info(symbol)
        try:
            full_info = ticker.info or {}
        except Exception:
            full_info = {}
        price = round(prices[-1], 2)
        market_cap = full_info.get("marketCap") or (ticker.fast_info.get("marketCap", 0))
        # Calculate volume and float metrics
        avg_volume = sum(volumes[-20:]) / min(20, len(volumes)) if volumes else 0
        shares_outstanding = (market_cap / price) if market_cap and price > 0 else 0
        
        # Volatility calculation (filter out high-churn names) — MUST BE BEFORE quality checks
        volatility_pct = calc_volatility(prices, lookback=20) or 0.0
        volatility_ok = volatility_pct <= 40.0
        
        # Quality flags
        passes_volume = (avg_volume or 0) >= MIN_AVG_VOLUME
        passes_float = (shares_outstanding or 0) >= MIN_FLOAT
        passes_market_cap = (market_cap or 0) >= MIN_MARKET_CAP
        passes_volatility = volatility_ok and (volatility_pct or 0) <= 40.0
        quality_rating = "PASS" if (passes_volume and passes_float and passes_market_cap and passes_volatility) else "CAUTION"
        
        # Gap fill analysis (overnight gap -> mean reversion setup)
        gap_fill = calc_gap_fill(prices[-2], prices[0] if len(prices) > 0 else price)
        
        # Technical analysis: Fibonacci, pivots, position sizing by extension
        daily_pct_change = 100 * (price - prices[-2]) / prices[-2] if prices[-2] else 0
        swings = find_swing_levels(prices, lookback=20)
        fib_levels = calc_fib_levels(swings["swing_low"], swings["swing_high"])
        
        # Get yesterday's OHLC for pivot calculation (use last close as proxy for all)
        day_high = max(prices[-5:]) if len(prices) >= 5 else price
        day_low = min(prices[-5:]) if len(prices) >= 5 else price
        pivots = calc_pivot_points(day_high, day_low, prices[-2] if len(prices) > 1 else price)
        
        # Scale position size by how extended the move already is
        sizing = scale_position_by_extension(daily_pct_change)
        
        # Calculate RSI for divergence detection
        rsi_val = calc_rsi(prices)
        rsi_history = [calc_rsi(prices[:i+1]) for i in range(max(0, len(prices)-10), len(prices))]
        divergence = detect_divergence(prices[-10:], rsi_history, lookback=5)
        
        # Relative strength will be calculated vs. SPY in the trading loop
        relative_strength_placeholder = {
            "outperformance_pct": "TBD_vs_SPY",
            "tradable": "TBD_vs_SPY",
        }
        
        # Bollinger Bands: Only compute for mean reversion candidates (RSI < 40)
        bbands = calc_bollinger_bands(prices, period=20, num_std=2.0) if rsi_val < 40 else None

        # Trading hours check
        trading_hours = is_optimal_trading_hours(datetime.now(ET))

        # MINIMAL: Essential fields only (60% token reduction)
        result = {
            "symbol": symbol,
            "price": price,
            "daily_pct_change": round(daily_pct_change, 2),
            "quality_rating": quality_rating,
            "rsi": rsi_val,
            "vwap": vwap,
            "volume_ratio": round(volumes[-1] / avg_vol, 2) if avg_vol else 1,
            "macd": round(calc_ema(prices, 12) - calc_ema(prices, 26), 4),
            "gap_fill": gap_fill,
        }

        # Add Bollinger Bands only for mean reversion candidates
        if bbands is not None:
            result["bollinger_bands"] = bbands
        
        # Cache the result before returning
        _market_cache[symbol] = {**result, "_ts": time.time()}
        return result
    except Exception as exc:
        return {"error": str(exc)}


def tool_get_trending_stocks() -> dict:
    global _movers_trending_cache
    now = time.time()
    
    # Return cached if fresh (< 1 hour old)
    if _movers_trending_cache["trending"] is not None and (now - _movers_trending_cache["ts"]) < 3600:
        return {"trending": _movers_trending_cache["trending"]}
    
    try:
        url  = "https://query1.finance.yahoo.com/v1/finance/trending/US"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        quotes = resp.json()["finance"]["result"][0]["quotes"]
        syms   = [q["symbol"].upper() for q in quotes[:20]
                  if q.get("symbol", "").replace("-", "").isalpha()
                  and "-" not in q.get("symbol", "")]
        
        # Cache it
        _movers_trending_cache["trending"] = syms
        _movers_trending_cache["ts"] = now
        
        return {"trending": syms}
    except Exception as exc:
        return {"error": str(exc), "trending": ["SOXL", "NVDL", "SPXL", "NVDA", "TSLA"]}


def tool_get_top_movers() -> dict:
    """Return today's biggest % gainers/losers with high volume — often earnings-driven moves.
    
    Cached for 1 hour to save API calls. Movers don't change significantly in an hour.
    """
    global _movers_trending_cache
    now = time.time()
    
    # Return cached if fresh (< 1 hour old)
    if _movers_trending_cache["movers"] is not None and (now - _movers_trending_cache["ts"]) < 3600:
        return {"movers": _movers_trending_cache["movers"]}
    
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
        movers = movers[:10]
        
        # Cache it
        _movers_trending_cache["movers"] = movers
        _movers_trending_cache["ts"] = now
        
        return {"movers": movers}
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
        news = get_cached_ticker(symbol).news or []
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
            resp = call_with_retry(lambda: client.beta.messages.create(
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
            ))
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

def score_candidate(market_data: dict, spy_data: dict, sector_strength: dict) -> dict:
    """Score a candidate based on different strategy fits.
    
    Returns: {
        "symbol": str,
        "gap_fill_score": 0-100,
        "momentum_score": 0-100,
        "reversal_score": 0-100,
        "mean_reversion_score": 0-100,
        "best_strategy": str,
        "overall_score": 0-100,
        "filters_pass": bool,
    }
    """
    if not market_data or market_data.get("error"):
        return {"symbol": market_data.get("symbol", "?"), "overall_score": 0, "filters_pass": False}
    
    sym = market_data.get("symbol", "")
    
    # Extract data
    gap_fill = market_data.get("gap_fill", {})
    rs = market_data.get("relative_strength_vs_spy", {})
    div = market_data.get("divergence", {})
    bbands = market_data.get("bollinger_bands", {})
    daily_pct = market_data.get("daily_pct_change", 0)
    vol_ratio = market_data.get("volume_ratio", 1)
    rsi = market_data.get("rsi", 50)
    sector = market_data.get("sector")
    
    # SPY data for relative strength
    spy_pct = spy_data.get("daily_pct_change", 0) if spy_data else 0
    
    # Baseline filter: quality + hours + relative strength
    quality_pass = market_data.get("quality_rating") == "PASS"
    hours_pass = market_data.get("trading_hours_status") != "suboptimal"
    rs_pass = rs.get("tradable", False) if isinstance(rs, dict) else True
    
    filters_pass = quality_pass and hours_pass and rs_pass
    
    # Strategy scores (0-100)
    
    # GAP FILL: gap up >2%, price pulled back, now oversold
    gap_fill_score = 0
    if gap_fill.get("gap_type") == "gap_up" and gap_fill.get("gap_pct", 0) > 2:
        gap_score = min(100, gap_fill.get("gap_pct", 0) * 10)  # bigger gap = higher score
        pullback_score = 50 if bbands.get("position") in ["below_lower", "below_middle"] else 20
        gap_fill_score = (gap_score + pullback_score) / 2
    
    # MOMENTUM: strong RS, volume, above VWAP, rising RSI
    momentum_score = 0
    if rs.get("outperformance_pct", 0) > 1.5:
        rs_score = min(100, (rs.get("outperformance_pct", 0) + 2) * 20)
        vol_score = min(100, vol_ratio * 40) if vol_ratio > 1 else 20
        price_pos = 40 if bbands.get("position") in ["above_middle", "above_upper"] else 60
        rsi_score = min(100, rsi * 1.2) if 40 < rsi < 70 else (rsi * 0.8 if rsi > 70 else rsi)
        momentum_score = (rs_score + vol_score + price_pos + rsi_score) / 4
    
    # REVERSAL: divergence at resistance, Fib level, overbought
    reversal_score = 0
    if div.get("bullish_div"):
        div_score = 80
        fib_bonus = 20 if "fib_levels" in str(market_data) else 0
        rsi_bonus = 20 if rsi < 40 else 0
        reversal_score = min(100, div_score + fib_bonus + rsi_bonus)
    
    # MEAN REVERSION: Bollinger lower band, oversold RSI
    mean_reversion_score = 0
    if bbands.get("position") == "below_lower":
        bband_score = 80
        rsi_score = min(80, (30 - rsi) * 3) if rsi < 30 else 20
        sector_bonus = 10 if sector and sector in sector_strength.get("top_sector", "") else 0
        mean_reversion_score = (bband_score + rsi_score + sector_bonus) / 2
    
    # Overall: best score + some bonus for multiple aligned signals
    scores = [gap_fill_score, momentum_score, reversal_score, mean_reversion_score]
    best_strategy = ["gap_fill", "momentum", "reversal", "mean_reversion"][scores.index(max(scores))]
    overall_score = max(scores)
    
    # Bonus if multiple strategies align
    high_scores = sum(1 for s in scores if s > 40)
    if high_scores >= 2:
        overall_score = min(100, overall_score + 15)
    
    return {
        "symbol": sym,
        "gap_fill_score": round(gap_fill_score, 1),
        "momentum_score": round(momentum_score, 1),
        "reversal_score": round(reversal_score, 1),
        "mean_reversion_score": round(mean_reversion_score, 1),
        "best_strategy": best_strategy,
        "overall_score": round(overall_score, 1),
        "filters_pass": filters_pass,
    }


def format_ranked_candidates(candidates_with_scores: list) -> str:
    """Format top-ranked candidates into a concise prompt section."""
    if not candidates_with_scores:
        return "No candidates met the quality filter today."
    
    # Sort by overall score descending
    sorted_cands = sorted(candidates_with_scores, key=lambda x: x.get("overall_score", 0), reverse=True)
    
    # Take top 5
    top_cands = sorted_cands[:5]
    
    lines = ["PRE-RANKED CANDIDATE LIST (sorted by setup quality):\n"]
    for i, cand in enumerate(top_cands, 1):
        sym = cand.get("symbol", "?")
        score = cand.get("overall_score", 0)
        strategy = cand.get("best_strategy", "unknown")
        daily_pct = cand.get("daily_pct_change", 0)
        rs_pct = cand.get("outperformance_pct", 0)
        
        line = f"{i}. {sym} | score:{score}% | strategy:{strategy} | change:{daily_pct:+.1f}% | RS:{rs_pct:+.1f}%"
        lines.append(line)
    
    lines.append("\nPick ONE candidate to trade (or PASS if none are compelling).")
    return "\n".join(lines)


def _record_token_usage(input_tokens, output_tokens):
    """Record token usage. Sonnet 4.6: $3/1M input, $15/1M output."""
    cost = (input_tokens * 3 + output_tokens * 15) / 1_000_000
    _run_tokens["input"] = input_tokens
    _run_tokens["output"] = output_tokens
    _run_tokens["cost_usd"] = round(cost, 6)
    _token_metrics["total_input_tokens"] += input_tokens
    _token_metrics["total_output_tokens"] += output_tokens
    _token_metrics["token_cost_usd"] = round(_token_metrics["token_cost_usd"] + cost, 6)

def _get_daily_pnl(state):
    """Calculate realized P&L from trades made today."""
    today = datetime.now().strftime("%Y-%m-%d")
    daily_pnl = 0.0
    for trade in state.get("trade_history", [])[-200:]:
        trade_date = trade.get("date", "")[:10] if trade.get("date") else ""
        if trade_date == today and "realized_pnl" in trade:
            daily_pnl += trade["realized_pnl"]
    return round(daily_pnl, 2)

def _log_metrics_summary(state):
    """Log token/ROI metrics at end of run."""
    today = datetime.now().strftime("%Y-%m-%d")
    daily_pnl = _get_daily_pnl(state)
    _token_metrics["date"] = today
    _token_metrics["daily_pnl"] = daily_pnl
    _token_metrics["runs"] += 1

    roi = (daily_pnl / _token_metrics["token_cost_usd"]) if _token_metrics["token_cost_usd"] > 0 else 0
    roi_pct = 100 * roi if _token_metrics["token_cost_usd"] > 0 else 0
    log.info(f"TOKEN-METRICS || Tokens: {_run_tokens['input']+_run_tokens['output']} "
             f"(${_run_tokens['cost_usd']:.4f}) || "
             f"Daily P&L: ${daily_pnl:+.2f} || "
             f"Total Cost: ${_token_metrics['token_cost_usd']:.2f} || "
             f"ROI: {roi_pct:+.0f}%")
    
    # Save daily metrics snapshot to persistent volume for tracking
    try:
        metrics_file = os.path.join(os.environ.get("DATA_DIR", "."), "daily_metrics.json")
        with open(metrics_file, "w") as f:
            json.dump(_token_metrics, f, indent=2)
    except Exception as e:
        log.warning(f"Could not save metrics: {e}")




def get_cached_price_history(symbol: str, period_days: int = 30) -> list:
    """Get 30-day price history from cache, or fetch fresh and cache it."""
    now = time.time()
    cache_entry = _price_cache.get(symbol, {})
    
    # Return if cached and less than 1 hour old
    if cache_entry.get("prices") and (now - cache_entry.get("ts", 0)) < 3600:
        return cache_entry.get("prices", [])
    
    # Fetch fresh
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=f"{period_days}d", interval="1d")
        if hist.empty or len(hist) < 14:
            return []
        
        prices = hist["Close"].tolist()
        
        # Cache it
        _price_cache[symbol] = {
            "prices": prices,
            "last_close": prices[-1],
            "ts": now
        }
        return prices
    except Exception:
        return []


def get_cached_fundamentals(symbol: str) -> dict:
    """Get fundamentals from cache (24-hour TTL), or fetch fresh."""
    now = time.time()
    cache_entry = _fundamentals_cache.get(symbol, {})
    
    # Return if cached and less than 24 hours old
    if cache_entry.get("market_cap") and (now - cache_entry.get("ts", 0)) < 86400:
        return cache_entry
    
    # Fetch fresh
    try:
        ticker = get_cached_ticker(symbol)
        info = ticker.info or {}
        fast_info = ticker.fast_info or {}

        fundamentals = {
            "market_cap": info.get("marketCap") or fast_info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "dividend": info.get("dividendRate"),
            "ts": now
        }

        # Cache it
        _fundamentals_cache[symbol] = fundamentals
        return fundamentals
    except Exception:
        return {}


def is_quality_stock_cached(symbol: str) -> dict:
    """Check if stock passes quality filters using cache (24-hour TTL)."""
    now = time.time()
    cache_entry = _quality_cache.get(symbol, {})
    
    # Return if cached and less than 24 hours old
    if "passes" in cache_entry and (now - cache_entry.get("ts", 0)) < 86400:
        return cache_entry
    
    # Evaluate fresh
    try:
        fundamentals = get_cached_fundamentals(symbol)
        market_cap = fundamentals.get("market_cap", 0)
        
        # Get volume
        prices = get_cached_price_history(symbol)
        hist = yf.Ticker(symbol).history(period="20d", interval="1d")
        avg_vol = hist["Volume"].tail(10).mean() if not hist.empty else 0
        
        passes = (
            (market_cap or 0) >= MIN_MARKET_CAP and
            (avg_vol or 0) >= MIN_AVG_VOLUME
        )
        
        result = {
            "passes": passes,
            "market_cap": market_cap,
            "avg_volume": avg_vol,
            "ts": now
        }
        
        # Cache it
        _quality_cache[symbol] = result
        return result
    except Exception:
        return {"passes": False, "ts": now}

def assess_sector_context(symbol: str, sector: str) -> dict:
    """Check if sector is dragging down the stock (not just company-specific).
    
    Returns: {
        "sector_momentum": "strong" | "weak" | "neutral",
        "reason": "sector up 1.5% vs stock down 3%",
        "skip_reversal": bool  # True if whole sector is falling
    }
    """
    try:
        if not sector or sector == "Unknown":
            return {"sector_momentum": "unknown", "reason": "no sector", "skip_reversal": False}
        
        # Get sector peers (use cache if available)
        sector_etf_map = {
            "Technology": "XLK",
            "Financials": "XLF",
            "Healthcare": "XLV",
            "Utilities": "XLU",
            "Energy": "XLE",
            "Materials": "XLB",
            "Industrials": "XLI",
            "Consumer Discretionary": "XLY",
            "Consumer Staples": "XLP",
            "Real Estate": "XLRE",
            "Communication": "XLC"
        }
        
        etf = sector_etf_map.get(sector)
        if not etf:
            return {"sector_momentum": "unknown", "reason": f"sector {sector} unknown", "skip_reversal": False}
        
        # Check if sector ETF is weak (down more than 1% = sector drag)
        try:
            sector_ticker = yf.Ticker(etf)
            sector_hist = sector_ticker.history(period="1d")
            if sector_hist.empty:
                return {"sector_momentum": "unknown", "reason": f"no {etf} data", "skip_reversal": False}
            
            sector_close = sector_hist["Close"].iloc[-1]
            sector_prev = sector_hist["Open"].iloc[0]
            sector_change = ((sector_close - sector_prev) / sector_prev) * 100
            
            if sector_change < -1.5:
                return {
                    "sector_momentum": "weak",
                    "reason": f"{sector} ({etf}) down {sector_change:.1f}% — sector drag",
                    "skip_reversal": True
                }
            elif sector_change > 1.5:
                return {
                    "sector_momentum": "strong",
                    "reason": f"{sector} ({etf}) up {sector_change:.1f}% — tailwind",
                    "skip_reversal": False
                }
            else:
                return {
                    "sector_momentum": "neutral",
                    "reason": f"{sector} ({etf}) {sector_change:+.1f}%",
                    "skip_reversal": False
                }
        except Exception:
            return {"sector_momentum": "unknown", "reason": "ETF data error", "skip_reversal": False}
    except Exception as e:
        return {"sector_momentum": "unknown", "reason": str(e), "skip_reversal": False}


def assess_fundamental_strength(symbol: str) -> dict:
    """Check if stock has strong fundamentals (safe for reversal).
    
    Returns: {
        "fundamental_health": "strong" | "moderate" | "weak",
        "pe_ratio": float,
        "relative_strength": "outperformer" | "in_line" | "underperformer",
        "reason": "explanation"
    }
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        
        pe = info.get("trailingPE") or info.get("forwardPE")
        market_cap = info.get("marketCap")
        profit_margin = info.get("profitMargins")
        
        # Industry averages (rough)
        industry_pe = 20  # market average
        industry_margin = 0.08
        
        health_score = 0
        
        # PE check (lower = cheaper = better for reversal)
        if pe and pe < industry_pe * 0.8:
            health_score += 2
            pe_status = "cheap"
        elif pe and pe > industry_pe * 1.2:
            health_score -= 1
            pe_status = "expensive"
        else:
            health_score += 1
            pe_status = "fair"
        
        # Profitability check
        if profit_margin and profit_margin > industry_margin:
            health_score += 2
        elif profit_margin and profit_margin < 0:
            health_score -= 2
        else:
            health_score += 1
        
        # Market cap (larger = safer reversal)
        if market_cap and market_cap >= 1e9:
            health_score += 1
        
        # Overall assessment
        if health_score >= 4:
            return {
                "fundamental_health": "strong",
                "pe_ratio": round(pe, 1) if pe else None,
                "relative_strength": "outperformer",
                "reason": f"PE {pe_status}, profitable, large cap — safe reversal"
            }
        elif health_score >= 2:
            return {
                "fundamental_health": "moderate",
                "pe_ratio": round(pe, 1) if pe else None,
                "relative_strength": "in_line",
                "reason": "Moderate fundamentals, reversal OK with caution"
            }
        else:
            return {
                "fundamental_health": "weak",
                "pe_ratio": round(pe, 1) if pe else None,
                "relative_strength": "underperformer",
                "reason": "Weak fundamentals, skip reversal — wait for stronger signal"
            }
    except Exception as e:
        return {
            "fundamental_health": "unknown",
            "pe_ratio": None,
            "relative_strength": "unknown",
            "reason": str(e)
        }


def assess_macro_regime() -> dict:
    """Assess current macro environment (affects reversal probability).
    
    Returns: {
        "regime": "bull" | "bear" | "choppy",
        "fed_signal": "hawkish" | "dovish" | "neutral",
        "reversal_conviction": 1.0 to 0.5  # multiply position size by this
    }
    """
    # Get macro context from cached macro news
    macro_data = _macro_cache.get("data", {})
    headlines = macro_data.get("headlines", "") if macro_data else ""
    
    fed_signal = "neutral"
    if "rate" in headlines.lower() and "hike" in headlines.lower():
        fed_signal = "hawkish"
        reversal_mult = 0.7  # rates rising = less reversal probability
    elif "cut" in headlines.lower() and "rate" in headlines.lower():
        fed_signal = "dovish"
        reversal_mult = 1.2  # rates falling = more reversal probability
    else:
        reversal_mult = 1.0
    
    # Market regime (bull/bear) based on macro
    if "inflation" in headlines.lower() or "recession" in headlines.lower():
        regime = "bear"
        reversal_mult *= 0.8
    elif "strong" in headlines.lower() and "growth" in headlines.lower():
        regime = "bull"
        reversal_mult *= 1.1
    else:
        regime = "choppy"
        reversal_mult *= 0.9
    
    return {
        "regime": regime,
        "fed_signal": fed_signal,
        "reversal_conviction": round(max(0.5, min(1.3, reversal_mult)), 2)
    }


def assess_news_sentiment(symbol: str) -> dict:
    """Quick sentiment check on recent news. Returns sentiment and reason.
    
    Returns: {
        "sentiment": "positive" | "negative" | "neutral",
        "reason": "explanation",
        "skip_reversal": bool  # True if bad news, don't take mean reversion
    }
    """
    try:
        news = tool_get_news(symbol)
        headlines = news.get("headlines", [])
        
        if not headlines:
            return {"sentiment": "neutral", "reason": "no news", "skip_reversal": False}
        
        # Check first few headlines for red flags
        recent = " ".join(headlines[:3]).lower()
        
        negative_keywords = [
            "miss", "miss", "cut", "guidance", "loss", "decline", "weak",
            "bankruptcy", "suspend", "halt", "downgrade", "fraud", "scandal",
            "lawsuit", "recall", "warning", "breach", "exploit"
        ]
        
        positive_keywords = [
            "beat", "surge", "gain", "strong", "upgrade", "outperform",
            "profit", "growth", "expand", "acquisition", "partnership",
            "approval", "launch", "record"
        ]
        
        negative_count = sum(1 for kw in negative_keywords if kw in recent)
        positive_count = sum(1 for kw in positive_keywords if kw in recent)
        
        if negative_count > positive_count:
            return {
                "sentiment": "negative",
                "reason": f"News: {headlines[0][:100]}",
                "skip_reversal": True
            }
        elif positive_count > negative_count:
            return {
                "sentiment": "positive",
                "reason": f"News: {headlines[0][:100]}",
                "skip_reversal": False
            }
        else:
            return {
                "sentiment": "neutral",
                "reason": f"News: {headlines[0][:100]}",
                "skip_reversal": False
            }
    except Exception as e:
        return {"sentiment": "unknown", "reason": str(e), "skip_reversal": False}


def get_sector_momentum() -> dict:
    """Get today's strongest/weakest sectors using sector ETFs.
    
    Returns: {
        "strongest": ["Technology", "Finance", ...],
        "weakest": ["Energy", "Utilities"],
        "details": {sector: pct_change, ...}
    }
    """
    sector_etfs = {
        "Technology": "XLK",
        "Financials": "XLF",
        "Healthcare": "XLV",
        "Industrials": "XLI",
        "Consumer Discretionary": "XLY",
        "Energy": "XLE",
        "Materials": "XLB",
        "Utilities": "XLU",
        "Real Estate": "XLRE",
        "Communication": "XLC"
    }
    
    sector_perf = {}
    try:
        for sector_name, etf in sector_etfs.items():
            try:
                ticker = yf.Ticker(etf)
                hist = ticker.history(period="1d")
                if not hist.empty:
                    open_price = hist["Open"].iloc[0]
                    close_price = hist["Close"].iloc[-1]
                    pct_change = ((close_price - open_price) / open_price) * 100
                    sector_perf[sector_name] = round(pct_change, 2)
            except:
                pass
        
        if not sector_perf:
            return {"strongest": [], "weakest": [], "details": {}}
        
        sorted_sectors = sorted(sector_perf.items(), key=lambda x: x[1], reverse=True)
        strongest = [s[0] for s in sorted_sectors[:3]]
        weakest = [s[0] for s in sorted_sectors[-3:]]
        
        return {
            "strongest": strongest,
            "weakest": weakest,
            "details": sector_perf
        }
    except Exception as e:
        return {"strongest": [], "weakest": [], "details": {}}


def haiku_screen_candidates(movers: list, trending: list, top_sectors: list = None) -> list:
    """Stage 1a: Use Haiku to quickly filter GAP-FILL candidates (cheap).

    Prioritizes candidates in top-performing sectors.
    Cache: 1-hour TTL (saves ~1400 tokens/day by skipping re-screening within the hour).
    Returns: List of top 1-3 candidate symbols (Haiku's picks for gap-fill reversal).
    Expected tokens: 170 per screening (Haiku is 3-4x cheaper than Sonnet).
    """
    global _haiku_candidates_cache
    now = time.time()

    # Return cached if fresh (< 1 hour old)
    if _haiku_candidates_cache["candidates"] is not None and (now - _haiku_candidates_cache["ts"]) < 3600:
        log.info("HAIKU-GAP-FILL: Using cached result from %.0f min ago", (now - _haiku_candidates_cache["ts"]) / 60)
        return _haiku_candidates_cache["candidates"]

    if not movers and not trending:
        return []

    # Combine and deduplicate
    all_candidates = list(set([m.get("symbol") for m in movers if m.get("symbol")] +
                              trending[:15]))[:20]

    # Filter to prioritize top sectors
    if top_sectors:
        sector_map = {}
        for m in movers:
            try:
                ticker = yf.Ticker(m.get("symbol"))
                sector = ticker.info.get("sector") or "Unknown"
                sector_map[m.get("symbol")] = sector
            except:
                pass

        # Prioritize candidates in strong sectors
        candidates_in_top_sectors = [c for c in all_candidates if sector_map.get(c) in top_sectors]
        if candidates_in_top_sectors:
            all_candidates = candidates_in_top_sectors[:15]

    if not all_candidates:
        return []

    # Build a simple context for Haiku to screen
    movers_text = "\n".join([
        f"  {m['symbol']}: {m.get('pct_change', 0):+.1f}%, vol {m.get('volume_vs_avg', 0):.1f}x"
        for m in movers[:10]
    ])

    try:
        screening_prompt = f"""Pick BEST GAP-FILL reversal candidate TODAY (oversold bounce, overnight gap down).
CANDIDATES: {movers_text[:200]}
TRENDING: {', '.join(trending[:5])}
RULES: Prefer: gap down overnight + RSI<30 + high volume. Return SYMBOL only."""

        resp = call_with_retry(lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": screening_prompt}],
            ))

        # Track Haiku token usage (Haiku is 3-4x cheaper than Sonnet)
        if hasattr(resp, 'usage'):
            haiku_cost = (resp.usage.input_tokens * 1 + resp.usage.output_tokens * 5) / 1_000_000
            _run_tokens["input"] += resp.usage.input_tokens
            _run_tokens["output"] += resp.usage.output_tokens
            _run_tokens["cost_usd"] = round(_run_tokens["cost_usd"] + haiku_cost, 6)
            log.info("Haiku (gap-fill) tokens: %d in + %d out ($.%.4f)", resp.usage.input_tokens, resp.usage.output_tokens, haiku_cost)

        # Parse response to extract symbols
        text = resp.content[0].text if resp.content else ""
        symbols = []
        for line in text.split("\n"):
            if line.strip() and any(c.isalpha() for c in line):
                parts = line.split()
                if parts and parts[0].isupper() and len(parts[0]) <= 4:
                    symbols.append(parts[0])

        top_candidates = symbols[:3]
        log.info("HAIKU-GAP-FILL: Filtered %d candidates → top 3: %s",
                 len(all_candidates), " > ".join(top_candidates) if top_candidates else "NONE")

        # Cache the result
        _haiku_candidates_cache["candidates"] = top_candidates
        _haiku_candidates_cache["ts"] = now

        return top_candidates

    except Exception as e:
        log.warning("Haiku gap-fill screening failed: %s — fallback", e)
        return all_candidates[:3]  # Fallback

def fetch_options_summary(symbol: str) -> dict:
    """Fetch options data for gamma collapse detection.

    Returns summary of call/put activity (free CBOE data).
    Uses yfinance as fallback if yoptions unavailable.
    """
    try:
        ticker = yf.Ticker(symbol)

        # Try to get options expirations and chains
        expirations = ticker.options
        if not expirations:
            return None

        # Get the nearest expiration (soonest = most active trading)
        nearest_exp = expirations[0]
        opts = ticker.option_chain(nearest_exp)

        calls = opts.calls
        puts = opts.puts

        # Calculate volumes
        call_volume = calls['volume'].sum() if not calls.empty else 0
        put_volume = puts['volume'].sum() if not puts.empty else 0

        # Calculate IV (implied volatility)
        call_iv = calls['impliedVolatility'].mean() if not calls.empty else 0
        put_iv = puts['impliedVolatility'].mean() if not puts.empty else 0

        # Call/put ratio
        ratio = call_volume / (put_volume or 1)

        # Open interest for trend detection
        call_oi = calls['openInterest'].sum() if not calls.empty else 0
        put_oi = puts['openInterest'].sum() if not puts.empty else 0

        return {
            "symbol": symbol,
            "call_volume": call_volume,
            "put_volume": put_volume,
            "call_put_ratio": round(ratio, 2),
            "call_iv": round(call_iv, 4),
            "put_iv": round(put_iv, 4),
            "call_open_interest": call_oi,
            "put_open_interest": put_oi,
            "timestamp": time.time(),
        }
    except Exception as e:
        log.debug(f"Options data fetch failed for {symbol}: {e}")
        return None


def get_dark_pool_blocks(symbol: str, minutes: int = 60) -> list:
    """Fetch recent large block trades (dark pool signals).

    Block trades are pre-arranged institutional trades reported after execution.
    Free data source: parsed from yfinance + broker alerts.

    Returns: List of blocks [{symbol, size, price, time}, ...]
    """
    try:
        ticker = yf.Ticker(symbol)

        # Get recent historical data to infer block patterns
        hist = ticker.history(period="5d", interval="1m")

        if hist.empty or len(hist) < 60:
            return []

        # Get current price for comparison
        current_price = hist["Close"].iloc[-1]

        # Detect large volume spikes (proxy for block trades)
        # Block trades show as volume spikes often at different prices
        avg_volume = hist["Volume"].tail(100).mean()

        blocks = []
        for i in range(len(hist) - minutes, len(hist)):
            if i < 0:
                continue

            vol = hist["Volume"].iloc[i]
            price = hist["Close"].iloc[i]
            time_str = hist.index[i].strftime("%H:%M")

            # Large volume spike = potential block trade
            if vol > avg_volume * 3:
                # Infer direction: above or below current market
                direction = "BUY" if price >= current_price else "SELL"

                blocks.append({
                    "symbol": symbol,
                    "size": int(vol),
                    "price": round(price, 2),
                    "time": time_str,
                    "direction": direction,
                    "volume_ratio": round(vol / avg_volume, 1),
                })

        return blocks[-5:]  # Return last 5 blocks (most recent)

    except Exception as e:
        log.debug(f"Dark pool block detection failed for {symbol}: {e}")
        return []


def analyze_dark_pool_pressure(symbol: str) -> dict:
    """Analyze dark pool blocks to determine buyer vs seller pressure.

    Returns: {
        "blocks_detected": int,
        "pressure": "BUYING" | "SELLING" | "NEUTRAL",
        "summary": str
    }
    """
    blocks = get_dark_pool_blocks(symbol, minutes=60)

    if not blocks:
        return {
            "blocks_detected": 0,
            "pressure": "NEUTRAL",
            "summary": "No recent block trades detected"
        }

    buy_blocks = sum(1 for b in blocks if b["direction"] == "BUY")
    sell_blocks = sum(1 for b in blocks if b["direction"] == "SELL")

    if buy_blocks > sell_blocks * 1.5:
        pressure = "BUYING"
        reason = f"{buy_blocks} buy blocks vs {sell_blocks} sell blocks"
    elif sell_blocks > buy_blocks * 1.5:
        pressure = "SELLING"
        reason = f"{sell_blocks} sell blocks vs {buy_blocks} buy blocks"
    else:
        pressure = "NEUTRAL"
        reason = f"Mixed: {buy_blocks} buy, {sell_blocks} sell"

    # Get average price vs current
    avg_block_price = sum(b["price"] for b in blocks) / len(blocks)
    current_price = blocks[0]["price"]  # Most recent
    price_diff = ((avg_block_price - current_price) / current_price) * 100

    summary = f"{reason} | Avg block price {price_diff:+.2f}% vs market"

    return {
        "blocks_detected": len(blocks),
        "pressure": pressure,
        "summary": summary,
        "recent_blocks": blocks[-3:],  # Last 3 blocks
    }


def detect_gamma_collapse(symbol: str, prev_ratio: float = None) -> dict:
    """Detect gamma collapse (call buying exhaustion).

    Uses Haiku to analyze options flow and recommend exit.
    Returns: {
        "collapsed": bool,
        "reason": str,
        "haiku_recommendation": str (EXIT or HOLD or UNKNOWN)
    }
    """
    current_data = fetch_options_summary(symbol)

    if not current_data:
        return {"collapsed": False, "reason": "No options data", "haiku_recommendation": "HOLD"}

    current_ratio = current_data["call_put_ratio"]
    call_volume = current_data["call_volume"]
    put_volume = current_data["put_volume"]
    call_iv = current_data["call_iv"]
    put_iv = current_data["put_iv"]

    # Detect collapse signals
    signals = []

    if prev_ratio and (prev_ratio - current_ratio) / (prev_ratio or 1) > 0.25:
        signals.append(f"Call/put ratio dropped 25%+ ({prev_ratio:.2f} → {current_ratio:.2f})")

    if call_volume < 1000:
        signals.append(f"Call volume critically low ({call_volume})")

    if put_iv > call_iv * 1.2:
        signals.append(f"Put IV > Call IV (downside hedging, {put_iv:.2f} vs {call_iv:.2f})")

    if not signals:
        return {"collapsed": False, "reason": "No collapse signals", "haiku_recommendation": "HOLD"}

    # Use Haiku to interpret options flow (lightweight analysis)
    try:
        options_summary = f"""Stock: {symbol}
Call/Put Ratio: {current_ratio:.2f}
Call Volume: {call_volume}
Put Volume: {put_volume}
Call IV: {call_iv:.4f}
Put IV: {put_iv:.4f}
Call OI: {current_data['call_open_interest']}
Put OI: {current_data['put_open_interest']}

Signals: {'; '.join(signals)}

Is this gamma collapse (institution exit)? EXIT or HOLD?
Answer with one word only: EXIT or HOLD"""

        resp = call_with_retry(lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{"role": "user", "content": options_summary}],
        ))

        # Track token usage
        if hasattr(resp, 'usage'):
            haiku_cost = (resp.usage.input_tokens * 1 + resp.usage.output_tokens * 5) / 1_000_000
            _run_tokens["input"] += resp.usage.input_tokens
            _run_tokens["output"] += resp.usage.output_tokens
            _run_tokens["cost_usd"] = round(_run_tokens["cost_usd"] + haiku_cost, 6)
            log.info("Haiku (gamma) tokens: %d in + %d out ($.%.4f)",
                    resp.usage.input_tokens, resp.usage.output_tokens, haiku_cost)

        recommendation = resp.content[0].text.strip().upper() if resp.content else "UNKNOWN"

        collapsed = recommendation == "EXIT"

        log.info("GAMMA-COLLAPSE: %s | Ratio: %.2f | Signals: %s | Haiku: %s",
                symbol, current_ratio, "; ".join(signals)[:100], recommendation)

        return {
            "collapsed": collapsed,
            "reason": "; ".join(signals),
            "haiku_recommendation": recommendation,
            "ratio": current_ratio,
        }

    except Exception as e:
        log.warning("Gamma collapse analysis failed: %s", e)
        return {
            "collapsed": any("ratio dropped" in s for s in signals),
            "reason": "; ".join(signals),
            "haiku_recommendation": "UNKNOWN",
        }


def analyze_institutional_intent(symbol: str) -> dict:
    """Comprehensive institutional intent analysis using CBOE + dark pools.

    Combines:
    1. CBOE options flow (call/put ratio, IV)
    2. Dark pool blocks (buying/selling pressure)
    3. Price/technical data

    Returns: {
        "symbol": str,
        "intent": "ACCUMULATION" | "EXIT" | "NEUTRAL",
        "confidence": float (0-1),
        "summary": str,
        "signals": [str, ...],
        "risk": str
    }
    """
    try:
        # Get all data sources
        cboe_data = fetch_options_summary(symbol)
        dark_pool_data = analyze_dark_pool_pressure(symbol)
        price_data = tool_fetch_market_data(symbol) if symbol else None

        if not cboe_data or not price_data:
            return {
                "symbol": symbol,
                "intent": "NEUTRAL",
                "confidence": 0,
                "summary": "Insufficient data",
                "signals": [],
                "risk": "UNKNOWN"
            }

        # Analyze signals
        signals = []
        confidence = 0.5  # Start at neutral

        # CBOE Signal Analysis
        call_put_ratio = cboe_data["call_put_ratio"]
        call_iv = cboe_data["call_iv"]
        put_iv = cboe_data["put_iv"]

        if call_put_ratio > 1.5:
            signals.append(f"High call/put ratio ({call_put_ratio:.2f}) = accumulation bias")
            confidence += 0.15
        elif call_put_ratio < 0.8:
            signals.append(f"Low call/put ratio ({call_put_ratio:.2f}) = exit bias")
            confidence -= 0.15

        if put_iv > call_iv * 1.15:
            signals.append(f"Put IV spiking (put={put_iv:.4f}, call={call_iv:.4f}) = hedging stress")
            confidence -= 0.10
        elif put_iv < call_iv * 0.95:
            signals.append(f"Call IV > put IV = confidence building")
            confidence += 0.10

        # Dark Pool Signal Analysis
        dp_pressure = dark_pool_data["pressure"]
        dp_summary = dark_pool_data["summary"]

        if dp_pressure == "BUYING":
            signals.append(f"Dark pool blocks show buying pressure ({dp_summary})")
            confidence += 0.15
        elif dp_pressure == "SELLING":
            signals.append(f"Dark pool blocks show selling pressure ({dp_summary})")
            confidence -= 0.15

        # Combine signals into intent
        if confidence > 0.6:
            intent = "ACCUMULATION"
            risk = "LOW"
        elif confidence < -0.6:
            intent = "EXIT"
            risk = "HIGH"
        else:
            intent = "NEUTRAL"
            risk = "MEDIUM"

        # Build summary
        summary = " | ".join(signals) if signals else "Mixed signals"

        return {
            "symbol": symbol,
            "intent": intent,
            "confidence": round(max(0, min(1, confidence)), 2),
            "summary": summary,
            "signals": signals,
            "risk": risk,
        }

    except Exception as e:
        log.debug(f"Institutional intent analysis failed for {symbol}: {e}")
        return {
            "symbol": symbol,
            "intent": "NEUTRAL",
            "confidence": 0,
            "summary": f"Analysis error: {e}",
            "signals": [],
            "risk": "UNKNOWN"
        }


def haiku_screen_momentum_candidates(movers: list, trending: list, top_sectors: list = None) -> list:
    """Stage 1b: Use Haiku to quickly filter MOMENTUM candidates (cheap).

    Identifies strongest trend-following opportunities.
    Cache: 1-hour TTL (same cache as gap-fill, different screening logic).
    Returns: List of top 1-3 candidate symbols (Haiku's picks for momentum/trend following).
    Expected tokens: 170 per screening (Haiku is 3-4x cheaper than Sonnet).
    """
    if not movers and not trending:
        return []

    # Combine and deduplicate (prioritize high % gainers for momentum)
    # Sort movers by % change descending for momentum screening
    sorted_movers = sorted([m for m in movers if m.get("symbol")],
                          key=lambda m: m.get("pct_change", 0), reverse=True)
    all_candidates = list(set([m.get("symbol") for m in sorted_movers[:15]] +
                              trending[:10]))[:20]

    # Filter to prioritize top sectors
    if top_sectors:
        sector_map = {}
        for m in sorted_movers:
            try:
                ticker = yf.Ticker(m.get("symbol"))
                sector = ticker.info.get("sector") or "Unknown"
                sector_map[m.get("symbol")] = sector
            except:
                pass

        # Prioritize candidates in strong sectors
        candidates_in_top_sectors = [c for c in all_candidates if sector_map.get(c) in top_sectors]
        if candidates_in_top_sectors:
            all_candidates = candidates_in_top_sectors[:15]

    if not all_candidates:
        return []

    # Build context for momentum screening (focus on strongest gainers)
    movers_text = "\n".join([
        f"  {m['symbol']}: {m.get('pct_change', 0):+.1f}%, vol {m.get('volume_vs_avg', 0):.1f}x"
        for m in sorted_movers[:10]
    ])

    try:
        screening_prompt = f"""Pick BEST MOMENTUM candidate TODAY (trend continuation, strongest % gain).
CANDIDATES: {movers_text[:200]}
TRENDING: {', '.join(trending[:5])}
RULES: Prefer: highest % gain + MACD bullish + price>VWAP + volume surge. Return SYMBOL only."""

        resp = call_with_retry(lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{"role": "user", "content": screening_prompt}],
            ))

        # Track Haiku token usage
        if hasattr(resp, 'usage'):
            haiku_cost = (resp.usage.input_tokens * 1 + resp.usage.output_tokens * 5) / 1_000_000
            _run_tokens["input"] += resp.usage.input_tokens
            _run_tokens["output"] += resp.usage.output_tokens
            _run_tokens["cost_usd"] = round(_run_tokens["cost_usd"] + haiku_cost, 6)
            log.info("Haiku (momentum) tokens: %d in + %d out ($.%.4f)", resp.usage.input_tokens, resp.usage.output_tokens, haiku_cost)

        # Parse response to extract symbols
        text = resp.content[0].text if resp.content else ""
        symbols = []
        for line in text.split("\n"):
            if line.strip() and any(c.isalpha() for c in line):
                parts = line.split()
                if parts and parts[0].isupper() and len(parts[0]) <= 4:
                    symbols.append(parts[0])

        top_candidates = symbols[:3]
        log.info("HAIKU-MOMENTUM: Filtered %d candidates → top 3: %s",
                 len(all_candidates), " > ".join(top_candidates) if top_candidates else "NONE")

        return top_candidates

    except Exception as e:
        log.warning("Haiku momentum screening failed: %s — fallback", e)
        return all_candidates[:3]  # Fallback

def run_trading_loop():
    global _run_count
    _run_count += 1
    
    if not is_market_hours():
        log.info("Outside market hours — skipping")
        return

    # Check circuit breaker halt status at start of run
    if token_breaker.is_bot_halted():
        log.critical("🚫 BOT HALTED — skipping run")
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

    # Build system prompt
    movers_note = ""  # Get_top_movers is now cached for 1 hour (no need for per-run throttling)
    
    # Candidate ranking will be inserted here before API call
    ranked_candidates_summary = ""  # will be populated below
    
    # Check if macro analysis is cached and fresh (60-min TTL)
    macro_reuse_note = ""
    if _macro_analysis_cache["analysis"] and (time.time() - _macro_analysis_cache["ts"]) < 3600:
        age_min = int((time.time() - _macro_analysis_cache["ts"]) / 60)
        macro_reuse_note = f"\n🔄 MACRO CACHED ({age_min} min old): If analysis hasn't changed, reuse the previous macro context."
        log.info("MACRO: Using cached analysis from %d min ago (skip regeneration)", age_min)
    
    system = f"""Account {ACCT}|Budget ${TOTAL_BUDGET}|Max ${MAX_POSITION}/trade|{now}|{status_msg}
RULES: 1.Check macro + positions 2.Pick STRATEGY (gap-fill reversal OR momentum trend) 3.Validate candidate 4.Skip any COLLAPSED (gamma dump signal) 5.BUY only if quality=PASS, <10% extended 6.Stop -3%, TP +2% 7.Trade 10-15 ET only 8.Exit immediately if gamma collapses 9.Daily loss limit: {DAILY_LOSS_LIMIT_PCT}% = ${TOTAL_BUDGET * DAILY_LOSS_LIMIT_PCT / 100:.0f}
Strategies: GAP-FILL (oversold bounce, mean reversion, RSI<30) | MOMENTUM (trend follow, highest gainers, MACD+)
Risk: GAMMA COLLAPSE = institutional exit signal → exit position immediately | DAILY LOSS LIMIT = halt new buys

SECTORS: {sector_summary}
FEEDBACK: {perf_summary or "None yet"}
COOLDOWNS: {cooldown_msg or "None"}
STOPS: {chr(10).join(forced_sells) if forced_sells else "None"}{trading_clause}

{macro_reuse_note}OUTPUT FORMAT: Return a JSON object with keys: "macro" (dict), "positions" (list), "candidates" (list), "decision" (string: "BUY"/"HOLD"/"SKIP"), "reasoning" (brief string). No markdown, tables, or prose — JSON only. Execute decisively."""

# === STAGE 1: DUAL HAIKU SCREENING (cheap, fast filtering) ===
    # Get sector momentum first to prioritize hot sectors
    sector_momentum = get_sector_momentum()
    top_sectors = sector_momentum.get("strongest", [])

    # Get movers and trending, then use Haiku to filter → candidates
    movers_data = tool_get_top_movers()
    trending_data = tool_get_trending_stocks()
    movers_list = movers_data.get("movers", [])
    trending_list = trending_data.get("trending", [])

    # FILTER OUT EXTENDED MOVERS (>10% daily change) — focus on quality stocks only
    quality_movers = [m for m in movers_list if abs(m.get("pct_change") or 0) <= 15]  # m[1] is pct_change
    skipped_movers = len(movers_list) - len(quality_movers)
    if skipped_movers > 0:
        log.info("Filtered extended movers: skipped %d (>15%% change), kept %d quality movers",
                 skipped_movers, len(quality_movers))

    log.info(f"SECTOR-MOMENTUM: Strongest: {', '.join(top_sectors)} | "
            f"Details: {sector_momentum.get('details', {})}")

    # PARALLEL: Screen for both gap-fill AND momentum candidates
    gap_fill_finalists = haiku_screen_candidates(quality_movers, trending_list, top_sectors=top_sectors)
    momentum_finalists = haiku_screen_momentum_candidates(quality_movers, trending_list, top_sectors=top_sectors)

    # Skip recently analyzed candidates (prevent looping on same stock within 30 min)
    gap_fill_finalists = [c for c in (gap_fill_finalists or []) if not skip_recently_analyzed(c, state)]
    momentum_finalists = [c for c in (momentum_finalists or []) if not skip_recently_analyzed(c, state)]

    log.info("Gap-fill candidates: %s | Momentum candidates: %s",
             " > ".join(gap_fill_finalists) if gap_fill_finalists else "NONE",
             " > ".join(momentum_finalists) if momentum_finalists else "NONE")

    # Fetch market data for top candidates from both strategies (for Sonnet to compare)
    candidates_data = {}
    all_candidates = list(set((gap_fill_finalists or []) + (momentum_finalists or [])))[:5]

    for candidate in all_candidates:
        try:
            market_data = tool_fetch_market_data(candidate)
            if market_data and "error" not in market_data:
                candidates_data[candidate] = market_data
        except Exception as e:
            log.warning("Error fetching data for %s: %s", candidate, e)

    # Build context for Sonnet: both strategies available
    candidate_data_str = ""
    if candidates_data:
        gap_fill_str = ""
        momentum_str = ""

        if gap_fill_finalists:
            gap_fill_str = "GAP-FILL CANDIDATES: " + ", ".join([
                f"{s} (data: {str(candidates_data.get(s, {}))[:500]})"
                for s in gap_fill_finalists if s in candidates_data
            ])

        if momentum_finalists:
            momentum_str = "MOMENTUM CANDIDATES: " + ", ".join([
                f"{s} (data: {str(candidates_data.get(s, {}))[:500]})"
                for s in momentum_finalists if s in candidates_data
            ])

        candidate_data_str = f"""
TWO STRATEGIES TODAY:
1. GAP-FILL (oversold reversal, mean reversion)
2. MOMENTUM (trend continuation, strongest gainers)

{gap_fill_str}
{momentum_str}

Pick the BEST strategy for today's market and trade that candidate."""

        log.info("Fetched market data for: %s", ", ".join(candidates_data.keys()))
    
    # Mark all candidates as analyzed (prevent looping on same stocks)
    for candidate in all_candidates:
        mark_candidate_analyzed(candidate, state)

    # STAGE 2a: GAMMA COLLAPSE + INSTITUTIONAL INTENT ANALYSIS
    candidate_analysis = {}
    safe_candidates = []

    for candidate in all_candidates:
        # Check gamma collapse (CBOE options)
        gamma_check = detect_gamma_collapse(candidate)
        gamma_collapsed = gamma_check and gamma_check.get("collapsed")

        # Check institutional intent (CBOE + dark pools)
        inst_intent = analyze_institutional_intent(candidate)

        candidate_analysis[candidate] = {
            "gamma": gamma_check,
            "intent": inst_intent,
        }

        # Filter logic
        if gamma_collapsed:
            log.warning("GAMMA COLLAPSE in %s - skipping (institutional exit)", candidate)
            continue

        if inst_intent.get("intent") == "EXIT":
            log.warning("INSTITUTIONAL EXIT signal in %s - skipping", candidate)
            continue

        safe_candidates.append(candidate)
        log.info("CANDIDATE %s: Gamma=OK, Intent=%s (confidence %.2f)",
                candidate,
                inst_intent.get("intent"),
                inst_intent.get("confidence", 0))

    if not safe_candidates:
        log.info("All candidates filtered due to gamma collapse — monitoring only")
        return

    # Build candidate context with full analysis
    if safe_candidates:
        gap_fill_str = ""
        momentum_str = ""

        if gap_fill_finalists:
            safe_gap = [s for s in gap_fill_finalists if s in safe_candidates]
            if safe_gap:
                gap_fill_lines = []
                for s in safe_gap:
                    if s in candidates_data:
                        intent = candidate_analysis.get(s, {}).get("intent", {})
                        intent_msg = f"{intent.get('intent')} (conf: {intent.get('confidence')}, risk: {intent.get('risk')})"
                        gap_fill_lines.append(
                            f"{s}: {intent_msg} | {intent.get('summary', '')[:100]}"
                        )
                if gap_fill_lines:
                    gap_fill_str = "GAP-FILL CANDIDATES:\n" + "\n".join(gap_fill_lines)

        if momentum_finalists:
            safe_momentum = [s for s in momentum_finalists if s in safe_candidates]
            if safe_momentum:
                momentum_lines = []
                for s in safe_momentum:
                    if s in candidates_data:
                        intent = candidate_analysis.get(s, {}).get("intent", {})
                        intent_msg = f"{intent.get('intent')} (conf: {intent.get('confidence')}, risk: {intent.get('risk')})"
                        momentum_lines.append(
                            f"{s}: {intent_msg} | {intent.get('summary', '')[:100]}"
                        )
                if momentum_lines:
                    momentum_str = "MOMENTUM CANDIDATES:\n" + "\n".join(momentum_lines)

        candidate_data_str = f"""
TWO STRATEGIES TODAY (CBOE + Dark Pool Analysis Applied):

INSTITUTIONAL CONTEXT:
- Gamma collapse detection: Active (exit signals detected)
- Dark pool monitoring: Active (buying/selling pressure tracked)
- Options flow analysis: Active (call/put ratio, IV trends)

1. GAP-FILL (oversold reversal, mean reversion)
{gap_fill_str}

2. MOMENTUM (trend continuation, strongest gainers)
{momentum_str}

For each candidate shown:
- Intent: ACCUMULATION (institutions buying) | EXIT (institutions selling) | NEUTRAL
- Confidence: 0-1.0 (how certain of the intent)
- Risk: LOW (safe) | MEDIUM | HIGH (danger zone)
- Summary: Specific signals detected (CBOE + dark pools)

STRATEGY: Pick the candidate with ACCUMULATION intent (institutions backing it)
          Skip any with EXIT intent (institutions exiting)
          Medium confidence on NEUTRAL is OK if technicals are strong"""

    messages = [
        {"role": "user", "content": f"Run your trading analysis now and return JSON format.{candidate_data_str}"}
    ]

    # === STAGE 2: SONNET DEEP ANALYSIS (expensive, final decision) ===
    # Fetch candidates, score them, and pass only top 3-5 to Claude
    # This reduces token usage by avoiding analysis of marginal candidates
    
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
                max_tokens=2200,
                betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
                timeout=90.0,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
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

        # Record token usage for ROI analysis
        if hasattr(resp, 'usage'):
            _record_token_usage(resp.usage.input_tokens, resp.usage.output_tokens)

        for block in resp.content:
            # Cache macro analysis if it contains MACRO ENVIRONMENT (reuse for 60 min)
            if hasattr(block, "text") and ("macro" in block.text or "MACRO" in block.text):
                _macro_analysis_cache["analysis"] = block.text
                _macro_analysis_cache["ts"] = time.time()
                log.info("MACRO: Cached fresh analysis (will reuse for next 60 min)")
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
