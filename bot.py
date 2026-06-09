"""
Multi-stock RSI + MACD + VWAP + Opening Range Breakout Trading Bot
Stocks: META, MUU, TSLA
Account: Robinhood Agentic ••••1949
Budget: $500 split equally (~$166 per stock)

Railway deployment — reads ANTHROPIC_API_KEY from environment variable.
Logs stream directly to Railway's log console.
"""

import anthropic
import yfinance as yf
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

STOCKS        = ["META", "MUU", "TSLA"]
TOTAL_BUDGET  = 500
PER_STOCK     = TOTAL_BUDGET // len(STOCKS)
ACCT          = "432591949"
ET            = ZoneInfo("America/New_York")

RSI_BUY         = 30
RSI_SELL        = 70
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

state = {
    sym: {
        "buy_at":    None,
        "trades":    0,
        "pnl":       0.0,
        "orb_high":  None,  # opening range high
        "orb_low":   None,  # opening range low
        "orb_date":  None,  # date ORB was calculated for
    }
    for sym in STOCKS
}
session_trades   = 0
session_pnl      = 0.0
trading_halted   = False  # set True when daily loss limit hit


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

        # Daily data for RSI/MACD/EMA (needs 30+ bars)
        daily = ticker.history(period="60d", interval="1d")
        if daily.empty or len(daily) < 30:
            log.warning("%s: insufficient daily history", symbol)
            return None
        prices  = daily["Close"].tolist()
        volumes = daily["Volume"].tolist()
        info    = ticker.fast_info

        # Intraday 5-min data for ORB and current price
        intraday = ticker.history(period="2d", interval="5m")
        today    = datetime.now(ET).date()
        if not intraday.empty:
            intraday.index = intraday.index.tz_convert(ET)
            today_bars = intraday[intraday.index.date == today]
        else:
            today_bars = intraday  # empty fallback

        return {
            "price":       round(prices[-1], 4),
            "prev_close":  round(prices[-2], 4),
            "prices_30d":  prices[-30:],
            "volumes":     volumes[-30:],
            "volume":      volumes[-1],
            "avg_volume":  info.three_month_average_volume or 1,
            "today_bars":  today_bars,  # 5-min bars for today
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

    prices      = data["prices_30d"]
    volumes     = data["volumes"]
    price       = data["price"]
    vol_ratio   = data["volume"] / (data["avg_volume"] or 1)
    today_bars  = data["today_bars"]

    rsi  = calc_rsi(prices)
    macd = calc_macd(prices)
    vwap = calc_vwap(prices, volumes)
    e9   = calc_ema(prices, 9)
    e20  = calc_ema(prices, 20)

    # ── Opening Range Breakout ──────────────────────────────────────────
    st       = state[symbol]
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

    buy_at    = st["buy_at"]
    reasons   = []
    buy_score = sell_score = 0

    # ── RSI ─────────────────────────────────────────────────────────────
    if rsi < RSI_BUY:
        buy_score += 1
        reasons.append(f"RSI {rsi:.1f} oversold")
    elif rsi > RSI_SELL:
        sell_score += 1
        reasons.append(f"RSI {rsi:.1f} overbought")
    else:
        reasons.append(f"RSI {rsi:.1f}")

    # ── MACD ─────────────────────────────────────────────────────────────
    if macd > 0:
        buy_score += 1
        reasons.append("MACD bullish")
    else:
        sell_score += 1
        reasons.append("MACD bearish")

    # ── VWAP ─────────────────────────────────────────────────────────────
    if price > vwap:
        buy_score += 1
        reasons.append("above VWAP")
    else:
        sell_score += 1
        reasons.append("below VWAP")

    # ── Volume ───────────────────────────────────────────────────────────
    if vol_ratio >= 2:
        buy_score += 1
        reasons.append(f"vol {vol_ratio:.1f}x")

    # ── Opening Range Breakout ───────────────────────────────────────────
    # ORB breakout counts as a strong buy/sell signal (weight 2)
    if orb_breakout_up and vol_ratio >= 1.5:
        buy_score += 2
        reasons.append(f"ORB breakout above ${orb_high:.2f}")
    elif orb_breakout_down and vol_ratio >= 1.5:
        sell_score += 2
        reasons.append(f"ORB breakdown below ${orb_low:.2f}")

    # ── Stop-loss / Take-profit ──────────────────────────────────────────
    if buy_at:
        chg_pct = (price - buy_at) / buy_at * 100
        if chg_pct <= -STOP_LOSS:
            sell_score += 3
            reasons.append(f"stop-loss {chg_pct:.1f}%")
        elif chg_pct >= TAKE_PROFIT:
            sell_score += 3
            reasons.append(f"take-profit +{chg_pct:.1f}%")

    # ── Signal logic ─────────────────────────────────────────────────────
    # ORB-driven entry: breakout up with volume confirmation is sufficient alone
    orb_buy_signal  = orb_breakout_up  and vol_ratio >= 1.5
    orb_sell_signal = orb_breakout_down and vol_ratio >= 1.5

    signal = "HOLD"
    if (buy_score >= 3 and rsi < RSI_BUY) or (orb_buy_signal and buy_score >= 2):
        signal = "BUY"
    elif (sell_score >= 2 and (rsi > RSI_SELL or buy_at)) or (orb_sell_signal and buy_at):
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
    global session_trades, session_pnl, trading_halted, _last_scan_date

    if not is_market_hours():
        now = datetime.now(ET).strftime("%H:%M ET")
        log.info("Outside market hours (%s) — skipping", now)
        return

    today = datetime.now(ET).date()
    if _last_scan_date != today:
        # New trading day — reset session state
        session_trades = 0
        session_pnl    = 0.0
        trading_halted = False
        _last_scan_date = today
        log.info("New trading day %s — session state reset.", today)

    now = datetime.now(ET).strftime("%H:%M ET")
    log.info("══════ scan at %s ══════", now)
    for sym in STOCKS:
        scan_symbol(sym)
    log.info("session trades=%d  P&L=%+.2f  halted=%s", session_trades, session_pnl, trading_halted)


def main() -> None:
    log.info("Multi-stock trading bot starting up")
    log.info("Stocks: %s  |  $%d per stock  |  scan every %dmin", STOCKS, PER_STOCK, SCAN_MINUTES)
    log.info("Market hours: 9:45-15:45 ET Mon-Fri")

    schedule.every(SCAN_MINUTES).minutes.do(scan_all)

    log.info("Running initial scan...")
    scan_all()

    while True:
        schedule.run_pending()
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
