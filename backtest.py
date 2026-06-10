"""
Backtest of the rule-based strategy described in README.md, using the same
indicator math as bot.py (calc_rsi, calc_ema, 30-day VWAP, 10-day volume ratio).

Rules (from README):
  BUY  — at least 3 of 4: RSI < 30, MACD > 0, price > VWAP, volume >= 2x 10d avg
  SELL — at least 2 of 3: RSI > 70, MACD < 0, price < VWAP
  Exit — stop-loss -3% / take-profit +5% from entry, checked against daily lows/highs

Sizing: $125 per position, $500 total budget, fractional shares.
Signals are computed on data up to each day's close and filled at that close.
Stops/TPs fill at the stop price when the day's range crosses it (stop checked
first when both are hit the same day — conservative).
"""

import json
import sys
from datetime import date

import yfinance as yf

SYMBOLS      = ["META", "MU", "TSLA", "NVDA", "SOXL", "SPXL", "NVDL"]
BENCHMARK    = "SPY"
YEARS        = 2
MAX_POSITION = 125.0
TOTAL_BUDGET = 500.0
STOP_LOSS    = 0.03
TAKE_PROFIT  = 0.05
LOOKBACK     = 30   # bot.py fetches 30d of history for its indicators


# ── identical math to bot.py ──────────────────────────────────────────────────

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


def indicators(closes, volumes):
    """Same fields tool_fetch_market_data derives from its 30d window."""
    n       = min(len(closes), len(volumes))
    vwap    = sum(closes[i] * volumes[i] for i in range(n)) / (sum(volumes[:n]) or 1)
    avg_vol = sum(volumes[-10:]) / 10
    return {
        "price":        closes[-1],
        "rsi":          calc_rsi(closes),
        "macd":         calc_ema(closes, 12) - calc_ema(closes, 26),
        "vwap":         vwap,
        "volume_ratio": volumes[-1] / avg_vol if avg_vol else 1,
    }


def buy_signal(ind):
    votes = [
        ind["rsi"] < 30,
        ind["macd"] > 0,
        ind["price"] > ind["vwap"],
        ind["volume_ratio"] >= 2.0,
    ]
    return sum(votes) >= 3, votes


def sell_signal(ind):
    votes = [
        ind["rsi"] > 70,
        ind["macd"] < 0,
        ind["price"] < ind["vwap"],
    ]
    return sum(votes) >= 2, votes


# ── backtest ──────────────────────────────────────────────────────────────────

def run():
    raw = yf.download(
        SYMBOLS + [BENCHMARK],
        period=f"{YEARS}y",
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
    )

    data = {}
    for sym in SYMBOLS + [BENCHMARK]:
        df = raw[sym].dropna()
        if len(df) < LOOKBACK + 10:
            print(f"skipping {sym}: only {len(df)} bars")
            continue
        data[sym] = df

    dates = sorted(set().union(*(set(df.index) for df in data.values())))

    cash      = TOTAL_BUDGET
    positions = {}            # sym -> {shares, entry, entry_date}
    trades    = []
    equity    = []            # (date, total value)

    for d in dates:
        # 1. manage open positions: stops, take-profits, sell signals
        for sym in list(positions):
            df = data.get(sym)
            if df is None or d not in df.index:
                continue
            pos  = positions[sym]
            row  = df.loc[d]
            exit_price = None
            reason     = None

            stop = pos["entry"] * (1 - STOP_LOSS)
            tp   = pos["entry"] * (1 + TAKE_PROFIT)
            if row["Low"] <= stop:
                exit_price, reason = stop, "stop-loss"
            elif row["High"] >= tp:
                exit_price, reason = tp, "take-profit"
            else:
                loc = df.index.get_loc(d)
                if loc >= LOOKBACK:
                    window = df.iloc[loc - LOOKBACK + 1: loc + 1]
                    ind = indicators(window["Close"].tolist(), window["Volume"].tolist())
                    hit, _ = sell_signal(ind)
                    if hit:
                        exit_price, reason = row["Close"], "sell-signal"

            if exit_price is not None:
                proceeds = pos["shares"] * exit_price
                cash    += proceeds
                pnl      = proceeds - pos["shares"] * pos["entry"]
                trades.append({
                    "symbol": sym, "entry_date": str(pos["entry_date"].date()),
                    "exit_date": str(d.date()), "entry": round(pos["entry"], 2),
                    "exit": round(exit_price, 2), "pnl": round(pnl, 2),
                    "pct": round(100 * (exit_price / pos["entry"] - 1), 2),
                    "reason": reason,
                })
                del positions[sym]

        # 2. look for entries
        for sym in SYMBOLS:
            if sym in positions or cash < 1:
                continue
            df = data.get(sym)
            if df is None or d not in df.index:
                continue
            loc = df.index.get_loc(d)
            if loc < LOOKBACK:
                continue
            window = df.iloc[loc - LOOKBACK + 1: loc + 1]
            ind = indicators(window["Close"].tolist(), window["Volume"].tolist())
            hit, votes = buy_signal(ind)
            if hit:
                dollars = min(MAX_POSITION, cash)
                price   = float(df.loc[d, "Close"])
                positions[sym] = {
                    "shares": dollars / price, "entry": price, "entry_date": d,
                }
                cash -= dollars

        # 3. mark to market
        value = cash
        for sym, pos in positions.items():
            df = data[sym]
            px = float(df.loc[d, "Close"]) if d in df.index else pos["entry"]
            value += pos["shares"] * px
        equity.append((d, value))

    # ── results ──────────────────────────────────────────────────────────────
    final  = equity[-1][1]
    ret    = 100 * (final / TOTAL_BUDGET - 1)
    peak   = mdd = 0.0
    for _, v in equity:
        peak = max(peak, v)
        mdd  = max(mdd, (peak - v) / peak)
    n_days = (equity[-1][0] - equity[0][0]).days
    spy    = data[BENCHMARK]
    spy_ret = 100 * (float(spy["Close"].iloc[-1]) / float(spy["Close"].iloc[LOOKBACK]) - 1)

    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    print(f"\nPeriod: {equity[0][0].date()} -> {equity[-1][0].date()}  ({n_days} days)")
    print(f"Universe: {', '.join(s for s in SYMBOLS if s in data)}")
    print(f"\nStarting budget : ${TOTAL_BUDGET:,.2f}")
    print(f"Final value     : ${final:,.2f}")
    print(f"Total return    : {ret:+.2f}%")
    print(f"Annualized      : {100 * ((final / TOTAL_BUDGET) ** (365 / n_days) - 1):+.2f}%")
    print(f"Avg daily return: {ret / max(len(equity), 1):+.4f}% per trading day")
    print(f"Max drawdown    : -{100 * mdd:.2f}%")
    print(f"SPY buy & hold  : {spy_ret:+.2f}% over same period")
    print(f"\nTrades: {len(trades)}  |  wins: {len(wins)}  losses: {len(losses)}"
          f"  |  win rate: {100 * len(wins) / len(trades):.0f}%" if trades else "\nTrades: 0")
    if positions:
        print(f"Still open: {', '.join(positions)}")
    print("\nTrade log:")
    for t in trades:
        print(f"  {t['symbol']:5} {t['entry_date']} -> {t['exit_date']}  "
              f"{t['pct']:+6.2f}%  ${t['pnl']:+8.2f}  ({t['reason']})")

    with open("backtest_results.json", "w") as f:
        json.dump({"final": final, "return_pct": ret, "max_drawdown_pct": 100 * mdd,
                   "trades": trades}, f, indent=2)


if __name__ == "__main__":
    run()
