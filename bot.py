"""
Multi-stock RSI + MACD + VWAP Trading Bot
Stocks: META, MUU, TSLA
Account: Robinhood Agentic ••••1949
Budget: $500 split equally (~$166 per stock)

Requirements:
    pip install anthropic yfinance schedule pytz

Usage:
    python bot.py

The bot runs automatically during market hours (9:45 AM - 3:45 PM ET).
Press Ctrl+C to stop.
"""

import anthropic
import yfinance as yf
import schedule
import time
import json
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trading_bot.log"),
    ],
)
log = logging.getLogger(__name__)

STOCKS       = ["META", "MUU", "TSLA"]
TOTAL_BUDGET = 500
PER_STOCK    = TOTAL_BUDGET // len(STOCKS)   # $166 each
ACCT         = "432591949"
ET           = ZoneInfo("America/New_York")

RSI_BUY      = 30
RSI_SELL     = 70
STOP_LOSS    = 3.0   # %
TAKE_PROFIT  = 5.0   # %
SCAN_MINUTES = 5

client = anthropic.Anthropic()

state = {
    sym: {"buy_at": None, "trades": 0, "pnl": 0.0}
    for sym in STOCKS
}
session_trades = 0
session_pnl    = 0.0


def is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=45, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=45, second=0, microsecond=0)
    return market_open <= now <= market_close


def calc_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        diff = prices[i] - prices[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period or 1e-9
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def calc_ema(prices: list[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1]
    k   = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 4)


def calc_macd(prices: list[float]) -> float:
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    macd  = ema12 - ema26
    signal_series = [
        calc_ema(prices[:len(prices) - 9 + i + 1], 12) -
        calc_ema(prices[:len(prices) - 9 + i + 1], 26)
        for i in range(9)
    ]
    signal = calc_ema(signal_series, 9)
    return round(macd - signal, 4)


def calc_vwap(prices: list[float], volumes: list[float]) -> float:
    n      = min(len(prices), len(volumes))
    tpv    = sum(prices[i] * volumes[i] for i in range(n))
    tv     = sum(volumes[:n]) or 1
    return round(tpv / tv, 4)


def fetch_market_data(symbol: str) -> dict | None:
    try:
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="60d", interval="1d")
        if hist.empty or len(hist) < 30:
            log.warning("%s: not enough history", symbol)
            return None
        prices  = hist["Close"].tolist()
        volumes = hist["Volume"].tolist()
        info    = ticker.fast_info
        return {
            "price":      round(prices[-1], 4),
            "prev_close": round(prices[-2], 4),
            "prices_30d": prices[-30:],
            "volumes":    volumes[-30:],
            "volume":     volumes[-1],
            "avg_volume": info.three_month_average_volume or 1,
        }
    except Exception as exc:
        log.error("%s: fetch failed — %s", symbol, exc)
        return None


def place_trade(symbol: str, side: str, price: float, reason: str) -> bool:
    log.info("%s: sending %s $%d to Robinhood via Claude AI...", symbol, side, PER_STOCK)
    try:
        resp = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            betas=["mcp-client-2025-04-04"],
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
                        f"First call review_equity_order to preview it, then call "
                        f"place_equity_order to execute. Signal reason: {reason}. "
                        f"Confirm the order ID and filled price in your reply."
                    ),
                }
            ],
        )
        reply = " ".join(
            b.text for b in resp.content if hasattr(b, "text")
        )
        log.info("%s %s order response: %s", symbol, side, reply[:200])
        return True
    except Exception as exc:
        log.error("%s: trade error — %s", symbol, exc)
        return False


def scan_symbol(symbol: str) -> None:
    global session_trades, session_pnl

    log.info("── scanning %s ──", symbol)
    data = fetch_market_data(symbol)
    if not data:
        return

    prices  = data["prices_30d"]
    volumes = data["volumes"]
    price   = data["price"]
    vol_ratio = data["volume"] / (data["avg_volume"] or 1)

    rsi  = calc_rsi(prices)
    macd = calc_macd(prices)
    vwap = calc_vwap(prices, volumes)
    e9   = calc_ema(prices, 9)
    e20  = calc_ema(prices, 20)

    log.info(
        "%s  price=$%.2f  RSI=%.1f  MACD=%+.3f  VWAP=$%.2f  "
        "EMA9=$%.2f  EMA20=$%.2f  vol=%.1fx",
        symbol, price, rsi, macd, vwap, e9, e20, vol_ratio,
    )

    st      = state[symbol]
    buy_at  = st["buy_at"]
    reasons = []
    buy_score = sell_score = 0

    if rsi < RSI_BUY:
        buy_score += 1
        reasons.append(f"RSI {rsi:.1f} oversold")
    elif rsi > RSI_SELL:
        sell_score += 1
        reasons.append(f"RSI {rsi:.1f} overbought")
    else:
        reasons.append(f"RSI {rsi:.1f}")

    if macd > 0:
        buy_score += 1
        reasons.append("MACD bullish")
    else:
        sell_score += 1
        reasons.append("MACD bearish")

    if price > vwap:
        buy_score += 1
        reasons.append("above VWAP")
    else:
        sell_score += 1
        reasons.append("below VWAP")

    if vol_ratio >= 2:
        buy_score += 1
        reasons.append(f"vol {vol_ratio:.1f}x")

    if buy_at:
        chg_pct = (price - buy_at) / buy_at * 100
        if chg_pct <= -STOP_LOSS:
            sell_score += 3
            reasons.append(f"stop-loss {chg_pct:.1f}%")
        elif chg_pct >= TAKE_PROFIT:
            sell_score += 3
            reasons.append(f"take-profit +{chg_pct:.1f}%")

    signal = "HOLD"
    if buy_score >= 3 and rsi < RSI_BUY:
        signal = "BUY"
    elif sell_score >= 2 and (rsi > RSI_SELL or buy_at):
        signal = "SELL"

    log.info("%s signal: %s  (%s)", symbol, signal, ", ".join(reasons))

    if signal == "BUY" and not buy_at:
        success = place_trade(symbol, "BUY", price, ", ".join(reasons))
        if success:
            st["buy_at"]  = price
            st["trades"] += 1
            session_trades += 1

    elif signal == "SELL" and buy_at:
        success = place_trade(symbol, "SELL", price, ", ".join(reasons))
        if success:
            pnl = (price - buy_at) / buy_at * PER_STOCK
            st["pnl"]    += round(pnl, 2)
            session_pnl  += round(pnl, 2)
            st["buy_at"]  = None
            st["trades"] += 1
            session_trades += 1
            log.info("%s trade P&L: %+.2f  session total: %+.2f", symbol, pnl, session_pnl)


def scan_all() -> None:
    if not is_market_hours():
        log.info("Outside market hours — skipping scan")
        return
    now = datetime.now(ET).strftime("%H:%M ET")
    log.info("═══ parallel scan at %s ═══", now)
    for sym in STOCKS:
        scan_symbol(sym)
    log.info(
        "session trades: %d  session P&L: %+.2f",
        session_trades, session_pnl,
    )


def print_banner() -> None:
    print("""
╔══════════════════════════════════════════════════════╗
║        Multi-Stock RSI + MACD + VWAP Bot             ║
║  Stocks : META · MUU · TSLA                          ║
║  Budget : $500 total  (~$166 per stock)              ║
║  Hours  : 9:45 AM – 3:45 PM ET (Mon–Fri)            ║
║  Interval: every 5 minutes                           ║
║  Account: Robinhood Agentic ••••1949                 ║
╚══════════════════════════════════════════════════════╝
Press Ctrl+C to stop.
""")


def main() -> None:
    print_banner()
    log.info("Bot starting up...")

    schedule.every(SCAN_MINUTES).minutes.do(scan_all)

    log.info("Running first scan now...")
    scan_all()

    log.info("Scheduled to scan every %d minutes during market hours.", SCAN_MINUTES)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot stopped by user. Final P&L: %+.2f", session_pnl)
        for sym in STOCKS:
            st = state[sym]
            log.info("  %s — trades: %d  P&L: %+.2f  position: %s",
                     sym, st["trades"], st["pnl"],
                     f"open @ ${st['buy_at']:.2f}" if st["buy_at"] else "none")
        sys.exit(0)
