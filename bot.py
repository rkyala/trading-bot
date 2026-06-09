"""
Multi-stock RSI + MACD + VWAP + Opening Range Breakout Trading Bot
Stocks: SOXL, MUU, SPXL + daily trending pick
Account: Robinhood Agentic ••••1949
Budget: $500 split equally (~$166 per stock)

Railway deployment — reads ANTHROPIC_API_KEY from environment variable.
Logs stream directly to Railway's log console.
"""

import anthropic
import yfinance as yf
import requests
import schedule
import time
import logging
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger(__name__)

FIXED_STOCKS  = ["SOXL", "MUU", "SPXL"]  # always traded
TOTAL_BUDGET  = 500
ACCT_STOCKS   = 4                         # total slots (fixed + 1 trending)
PER_STOCK     = TOTAL_BUDGET // ACCT_STOCKS
ACCT          = "432591949"
ET            = ZoneInfo("America/New_York")

# Stocks that use RSI-only signal logic (no MACD/VWAP/ORB)
RSI_ONLY_STOCKS = {"SPXL"}

# Excluded from trending pick (already in fixed list or unsuitable)
TRENDING_EXCLUDE = set(FIXED_STOCKS) | {"MUU"}

RSI_BUY         = 35    # more reachable on 5-min intraday data
RSI_SELL        = 65    # more reachable on 5-min intraday data
STOP_LOSS       = 3.0
TAKE_PROFIT     = 5.0
SCAN_MINUTES    = 5
ORB_MINUTES     = 15   # opening range window (first N minutes after open)
DAILY_LOSS_LIMIT = -15.0  # stop trading if session P&L drops below this ($)

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    log.error("ANTHROPIC_API_KEY environment variable not set. Exiting.")
    sys.exit(1)

client = anthropic.Anthropic(api_key=api_key)

def _empty_state():
    return {"buy_at": None, "trades": 0, "pnl": 0.0,
            "orb_high": None, "orb_low": None, "orb_date": None}

state          = {sym: _empty_state() for sym in FIXED_STOCKS}
STOCKS         = list(FIXED_STOCKS)   # will be extended with trending pick
session_trades = 0
session_pnl    = 0.0
trading_halted = False  # set True when daily loss limit hit


MIN_MARKET_CAP  = 10_000_000_000   # $10B minimum market cap
MAX_PE_RATIO    = 150              # skip bubble/loss-making stocks above this P/E
MIN_PE_RATIO    = 5                # skip stocks with suspiciously low or negative P/E
MIN_AVG_VOLUME  = 1_000_000        # at least 1M avg daily volume (liquidity)
MIN_WEEK_CHANGE = 2.0              # must be up at least 2% over past 5 days (sustained trend)


def fetch_trending_stock() -> str:
    """
    Pick the best trending US stock by:
    1. Pull Yahoo Finance trending list
    2. Skip indexes, crypto, penny stocks, excluded symbols
    3. Filter by market cap >= $10B, P/E 5–150, volume >= 1M
    4. Require >= 2% gain over past 5 days (not just a one-day spike)
    5. Return highest 5-day momentum among qualifiers
    """
    try:
        url    = "https://query1.finance.yahoo.com/v1/finance/trending/US"
        resp   = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        quotes = resp.json()["finance"]["result"][0]["quotes"]

        candidates = []
        for q in quotes:
            sym = q.get("symbol", "").upper()
            if not sym or sym in TRENDING_EXCLUDE or not sym.isalpha():
                continue
            try:
                ticker = yf.Ticker(sym)
                info   = ticker.fast_info

                mkt_cap    = getattr(info, "market_cap", None) or 0
                pe_ratio   = getattr(info, "pe_ratio", None)
                avg_vol    = getattr(info, "three_month_average_volume", None) or 0

                # ── Market cap filter ────────────────────────────────
                if mkt_cap < MIN_MARKET_CAP:
                    log.info("  %s skipped: market cap $%.1fB < $10B", sym, mkt_cap / 1e9)
                    continue

                # ── P/E ratio filter ─────────────────────────────────
                if pe_ratio is None or pe_ratio <= MIN_PE_RATIO or pe_ratio > MAX_PE_RATIO:
                    log.info("  %s skipped: P/E %.1f out of range %d–%d",
                             sym, pe_ratio or 0, MIN_PE_RATIO, MAX_PE_RATIO)
                    continue

                # ── Liquidity filter ─────────────────────────────────
                if avg_vol < MIN_AVG_VOLUME:
                    log.info("  %s skipped: avg volume %d < 1M", sym, avg_vol)
                    continue

                # ── Sustained trend: need 5-day price change >= 2% ──
                hist = ticker.history(period="6d", interval="1d")
                if len(hist) < 5:
                    continue
                week_chg = (hist["Close"].iloc[-1] - hist["Close"].iloc[-5]) / hist["Close"].iloc[-5] * 100
                if week_chg < MIN_WEEK_CHANGE:
                    log.info("  %s skipped: 5-day change %.1f%% < %.1f%%",
                             sym, week_chg, MIN_WEEK_CHANGE)
                    continue

                candidates.append((sym, week_chg, pe_ratio, mkt_cap))
                log.info("  %s qualified: P/E=%.1f  mktcap=$%.1fB  5d=+%.1f%%",
                         sym, pe_ratio, mkt_cap / 1e9, week_chg)

            except Exception as exc:
                log.debug("  %s info error: %s", sym, exc)
                continue

        if candidates:
            # Pick highest 5-day momentum among qualifiers
            best = sorted(candidates, key=lambda x: x[1], reverse=True)[0]
            log.info("Trending pick: %s  (P/E=%.1f  mktcap=$%.1fB  5d=+%.1f%%)",
                     best[0], best[2], best[3] / 1e9, best[1])
            return best[0]

    except Exception as exc:
        log.warning("Could not fetch trending stock: %s", exc)

    log.info("No trending stock passed filters — using fallback NVDA")
    return "NVDA"


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=45, second=0, microsecond=0)
    return market_open <= now <= market_close


def calc_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period or 1e-9
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def calc_ema(prices: list, period: int) -> float:
    if len(prices) < period:
        return prices[-1]
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 4)


def calc_macd(prices: list) -> float:
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    macd  = ema12 - ema26
    signal_series = [
        calc_ema(prices[:len(prices) - 9 + i + 1], 12) -
        calc_ema(prices[:len(prices) - 9 + i + 1], 26)
        for i in range(9)
    ]
    return round(macd - calc_ema(signal_series, 9), 4)


def calc_vwap(prices: list, volumes: list) -> float:
    n   = min(len(prices), len(volumes))
    tpv = sum(prices[i] * volumes[i] for i in range(n))
    tv  = sum(volumes[:n]) or 1
    return round(tpv / tv, 4)


def fetch_market_data(symbol: str) -> "dict | None":
    try:
        ticker = yf.Ticker(symbol)
        info   = ticker.fast_info

        # ── Intraday 5-min bars (primary data source for all signals) ──
        intraday = ticker.history(period="5d", interval="5m")
        if intraday.empty or len(intraday) < 15:
            log.warning("%s: insufficient intraday data", symbol)
            return None
        intraday.index = intraday.index.tz_convert(ET)
        today          = datetime.now(ET).date()
        today_bars     = intraday[intraday.index.date == today]

        # Use last 78 5-min bars (~1 full session) for RSI/MACD/EMA
        prices  = intraday["Close"].tolist()[-100:]
        volumes = intraday["Volume"].tolist()[-100:]

        # Current price = latest 5-min close
        price = round(prices[-1], 4)

        # Intraday VWAP = today only (resets each day)
        if not today_bars.empty:
            tp  = ((today_bars["High"] + today_bars["Low"] + today_bars["Close"]) / 3)
            vwap_today = round((tp * today_bars["Volume"]).sum() / today_bars["Volume"].sum(), 4)
        else:
            vwap_today = price

        # Volume ratio: today's total vs avg daily volume
        today_vol  = int(today_bars["Volume"].sum()) if not today_bars.empty else 0
        avg_vol    = info.three_month_average_volume or 1
        vol_ratio  = today_vol / avg_vol

        return {
            "price":       price,
            "prices":      prices,   # 5-min closes for RSI/MACD/EMA
            "volumes":     volumes,
            "volume":      today_vol,
            "avg_volume":  avg_vol,
            "vol_ratio":   vol_ratio,
            "vwap":        vwap_today,
            "today_bars":  today_bars,
        }
    except Exception as exc:
        log.error("%s: fetch error — %s", symbol, exc)
        return None


def calc_orb(symbol: str, today_bars) -> "tuple[float | None, float | None]":
    """Return (orb_high, orb_low) from first ORB_MINUTES of today's session."""
    if today_bars is None or today_bars.empty:
        return None, None
    market_open = datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
    orb_end     = market_open + timedelta(minutes=ORB_MINUTES)
    orb_bars    = today_bars[today_bars.index <= orb_end]
    if orb_bars.empty:
        return None, None
    return round(orb_bars["High"].max(), 4), round(orb_bars["Low"].min(), 4)


def place_trade(symbol: str, side: str, price: float, reason: str) -> bool:
    log.info("%s: requesting %s $%d via Claude + Robinhood MCP...", symbol, side, PER_STOCK)
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            mcp_servers=[
                {
                    "type": "url",
                    "url":  "https://agent.robinhood.com/mcp/trading",
                    "name": "Rh",
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Place a market {side} order for {symbol} on Robinhood account "
                        f"{ACCT} for ${PER_STOCK} USD. "
                        f"First call review_equity_order to preview, then place_equity_order "
                        f"to execute. Signal reason: {reason}. "
                        f"Reply with the order ID and filled price."
                    ),
                }
            ],
        )
        reply = " ".join(b.text for b in resp.content if hasattr(b, "text"))
        log.info("%s %s response: %s", symbol, side, reply[:200])
        return True
    except Exception as exc:
        log.error("%s: trade error — %s", symbol, exc)
        return False


def scan_symbol(symbol: str) -> None:
    global session_trades, session_pnl, trading_halted

    if trading_halted:
        log.warning("Trading halted — daily loss limit reached. Skipping %s.", symbol)
        return

    log.info("── scanning %s ──", symbol)
    data = fetch_market_data(symbol)
    if not data:
        return

    prices      = data["prices"]
    volumes     = data["volumes"]
    price       = data["price"]
    vol_ratio   = data["vol_ratio"]
    today_bars  = data["today_bars"]

    rsi  = calc_rsi(prices, period=14)
    st   = state[symbol]
    buy_at  = st["buy_at"]
    reasons = []
    signal  = "HOLD"

    if symbol in RSI_ONLY_STOCKS:
        # ── RSI-only strategy (NDX) ──────────────────────────────────────
        log.info("%s  $%.2f  RSI=%.1f  [RSI-only mode]", symbol, price, rsi)

        if rsi < RSI_BUY and not buy_at:
            reasons.append(f"RSI {rsi:.1f} oversold — BUY")
            signal = "BUY"
        elif rsi > RSI_SELL and buy_at:
            reasons.append(f"RSI {rsi:.1f} overbought — SELL")
            signal = "SELL"
        else:
            reasons.append(f"RSI {rsi:.1f} neutral")

        # Still honour stop-loss / take-profit for open NDX positions
        if buy_at:
            chg_pct = (price - buy_at) / buy_at * 100
            if chg_pct <= -STOP_LOSS:
                signal = "SELL"
                reasons.append(f"stop-loss {chg_pct:.1f}%")
            elif chg_pct >= TAKE_PROFIT:
                signal = "SELL"
                reasons.append(f"take-profit +{chg_pct:.1f}%")

    else:
        # ── Full strategy (SOXL, MUU, trending) ─────────────────────────
        macd = calc_macd(prices)
        vwap = data["vwap"]          # true intraday VWAP (resets daily)
        e9   = calc_ema(prices, 9)
        e20  = calc_ema(prices, 20)

        # ── Opening Range Breakout ─────────────────────────────────────
        today    = datetime.now(ET).date()
        orb_high = st["orb_high"]
        orb_low  = st["orb_low"]

        if st["orb_date"] != today:
            orb_high, orb_low = calc_orb(symbol, today_bars)
            st["orb_high"] = orb_high
            st["orb_low"]  = orb_low
            st["orb_date"] = today
            if orb_high and orb_low:
                log.info("%s  ORB set for today: high=$%.2f  low=$%.2f", symbol, orb_high, orb_low)

        orb_breakout_up   = orb_high and price > orb_high
        orb_breakout_down = orb_low  and price < orb_low

        log.info(
            "%s  $%.2f  RSI=%.1f  MACD=%+.3f  VWAP=$%.2f  EMA9=$%.2f  EMA20=$%.2f  "
            "vol=%.1fx  ORB=[%.2f/%.2f]  brk=%s",
            symbol, price, rsi, macd, vwap, e9, e20, vol_ratio,
            orb_high or 0, orb_low or 0,
            "UP" if orb_breakout_up else ("DN" if orb_breakout_down else "-"),
        )

        buy_score = sell_score = 0

        # RSI
        if rsi < RSI_BUY:
            buy_score += 1
            reasons.append(f"RSI {rsi:.1f} oversold")
        elif rsi > RSI_SELL:
            sell_score += 1
            reasons.append(f"RSI {rsi:.1f} overbought")
        else:
            reasons.append(f"RSI {rsi:.1f}")

        # MACD
        if macd > 0:
            buy_score += 1
            reasons.append("MACD bullish")
        else:
            sell_score += 1
            reasons.append("MACD bearish")

        # VWAP
        if price > vwap:
            buy_score += 1
            reasons.append("above VWAP")
        else:
            sell_score += 1
            reasons.append("below VWAP")

        # Volume
        if vol_ratio >= 2:
            buy_score += 1
            reasons.append(f"vol {vol_ratio:.1f}x")

        # ORB (weight 2)
        if orb_breakout_up and vol_ratio >= 1.5:
            buy_score += 2
            reasons.append(f"ORB breakout above ${orb_high:.2f}")
        elif orb_breakout_down and vol_ratio >= 1.5:
            sell_score += 2
            reasons.append(f"ORB breakdown below ${orb_low:.2f}")

        # Stop-loss / Take-profit
        if buy_at:
            chg_pct = (price - buy_at) / buy_at * 100
            if chg_pct <= -STOP_LOSS:
                sell_score += 3
                reasons.append(f"stop-loss {chg_pct:.1f}%")
            elif chg_pct >= TAKE_PROFIT:
                sell_score += 3
                reasons.append(f"take-profit +{chg_pct:.1f}%")

        orb_buy_signal  = orb_breakout_up  and vol_ratio >= 1.5
        orb_sell_signal = orb_breakout_down and vol_ratio >= 1.5

        # BUY: RSI oversold + 1 more confirm, OR ORB breakout alone with volume
        # SELL: RSI overbought OR 2 bearish signals with open position, OR ORB breakdown
        if (rsi < RSI_BUY and buy_score >= 2) or (orb_buy_signal and buy_score >= 1):
            signal = "BUY"
        elif (rsi > RSI_SELL and buy_at) or (sell_score >= 2 and buy_at) or (orb_sell_signal and buy_at):
            signal = "SELL"

    log.info("%s → %s  (%s)", symbol, signal, ", ".join(reasons))

    if signal == "BUY" and not buy_at:
        if place_trade(symbol, "BUY", price, ", ".join(reasons)):
            st["buy_at"]    = price
            st["trades"]   += 1
            session_trades += 1

    elif signal == "SELL" and buy_at:
        if place_trade(symbol, "SELL", price, ", ".join(reasons)):
            pnl             = (price - buy_at) / buy_at * PER_STOCK
            st["pnl"]      += round(pnl, 2)
            session_pnl    += round(pnl, 2)
            st["buy_at"]    = None
            st["trades"]   += 1
            session_trades += 1
            log.info("%s P&L this trade: %+.2f  session total: %+.2f", symbol, pnl, session_pnl)

            # Daily loss circuit breaker
            if session_pnl <= DAILY_LOSS_LIMIT:
                trading_halted = True
                log.warning(
                    "⚠️  Daily loss limit of $%.2f reached (session P&L: %+.2f). "
                    "Trading halted for today.", DAILY_LOSS_LIMIT, session_pnl
                )


_last_scan_date = None

def scan_all() -> None:
    global session_trades, session_pnl, trading_halted, _last_scan_date, STOCKS, state

    if not is_market_hours():
        now = datetime.now(ET).strftime("%H:%M ET")
        log.info("Outside market hours (%s) — skipping", now)
        return

    today = datetime.now(ET).date()
    if _last_scan_date != today:
        # New trading day — reset session state and refresh trending pick
        session_trades = 0
        session_pnl    = 0.0
        trading_halted = False
        _last_scan_date = today

        trending = fetch_trending_stock()
        STOCKS = list(FIXED_STOCKS) + [trending]
        # Add state entry for trending pick if not already present
        for sym in STOCKS:
            if sym not in state:
                state[sym] = _empty_state()

        log.info("New trading day %s — stocks: %s", today, STOCKS)

    now = datetime.now(ET).strftime("%H:%M ET")
    log.info("══════ scan at %s ══════", now)
    for sym in STOCKS:
        scan_symbol(sym)
    log.info("session trades=%d  P&L=%+.2f  halted=%s", session_trades, session_pnl, trading_halted)


def main() -> None:
    log.info("Multi-stock trading bot starting up")
    log.info("Fixed stocks: %s  |  trending pick fetched daily  |  $%d per stock  |  scan every %dmin",
             FIXED_STOCKS, PER_STOCK, SCAN_MINUTES)
    log.info("Market hours: 9:45-15:45 ET Mon-Fri")

    TURBO_MINUTES   = 1    # scan interval during turbo window
    TURBO_DURATION  = 30   # minutes to run at turbo interval on startup

    turbo_end = datetime.now(ET) + timedelta(minutes=TURBO_DURATION)
    log.info("⚡ Turbo mode: scanning every %dmin for the next %dmin (until %s ET)",
             TURBO_MINUTES, TURBO_DURATION, turbo_end.strftime("%H:%M"))

    schedule.every(TURBO_MINUTES).minutes.do(scan_all)

    log.info("Running initial scan...")
    scan_all()

    normal_schedule_set = False
    while True:
        schedule.run_pending()

        if not normal_schedule_set and datetime.now(ET) >= turbo_end:
            schedule.clear()
            schedule.every(SCAN_MINUTES).minutes.do(scan_all)
            normal_schedule_set = True
            log.info("⏱ Turbo window ended — switching to normal %dmin interval", SCAN_MINUTES)

        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot stopped. Final session P&L: %+.2f", session_pnl)
        for sym in STOCKS:
            st = state[sym]
            log.info("  %s  trades=%d  P&L=%+.2f  position=%s",
                     sym, st["trades"], st["pnl"],
                     f"open@${st['buy_at']:.2f}" if st["buy_at"] else "none")
        sys.exit(0)
