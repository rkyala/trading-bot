"""
Strategy comparison backtest — runs all variants over the same window:

  original  — README rules: 3-of-4 buy votes, 2-of-3 sell votes, -3% SL, +5% TP
  meanrev   — buy RSI<30 AND price<VWAP (truly oversold); exit when RSI>50; -3% SL
  momentum  — buy price>VWAP AND MACD>0 AND volume>=2x; -3% initial stop that
              trails 5% below the highest high since entry; no profit cap

Each variant runs with and without a regime filter (long entries only when
SPY close > its 50-day SMA). Indicator math is identical to bot.py.
Sizing: $125 per position, $500 total budget, fractional shares, fills at close;
stops fill at the stop price (checked before profit exits — conservative).
No slippage/fees modeled.
"""

import json

import yfinance as yf

SYMBOLS      = ["META", "MU", "TSLA", "NVDA", "SOXL", "SPXL", "NVDL"]
BENCHMARK    = "SPY"
MAX_POSITION = 125.0
TOTAL_BUDGET = 500.0
STOP_LOSS    = 0.03
TAKE_PROFIT  = 0.05
TRAIL_PCT    = 0.05
REGIME_SMA   = 50
LOOKBACK     = 30


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


# ── strategy definitions ──────────────────────────────────────────────────────

def entry_original(ind):
    return sum([ind["rsi"] < 30, ind["macd"] > 0,
                ind["price"] > ind["vwap"], ind["volume_ratio"] >= 2.0]) >= 3

def entry_meanrev(ind):
    return ind["rsi"] < 30 and ind["price"] < ind["vwap"]

def entry_momentum(ind):
    return ind["price"] > ind["vwap"] and ind["macd"] > 0 and ind["volume_ratio"] >= 2.0


STRATEGIES = {
    "original": {"entry": entry_original, "exit": "fixed"},
    "meanrev":  {"entry": entry_meanrev,  "exit": "rsi_recover"},
    "momentum": {"entry": entry_momentum, "exit": "trailing"},
}


# ── simulation ────────────────────────────────────────────────────────────────

def simulate(data, dates, spy_ok, strategy, use_filter):
    entry_fn  = STRATEGIES[strategy]["entry"]
    exit_mode = STRATEGIES[strategy]["exit"]

    cash, positions, trades, equity = TOTAL_BUDGET, {}, [], []

    for d in dates:
        # exits
        for sym in list(positions):
            df = data.get(sym)
            if df is None or d not in df.index:
                continue
            pos, row = positions[sym], df.loc[d]
            exit_price = reason = None

            op = float(row["Open"])
            if exit_mode == "trailing":
                stop = max(pos["entry"] * (1 - STOP_LOSS), pos["peak"] * (1 - TRAIL_PCT))
                if op <= stop:
                    exit_price, reason = op, "trail-stop-gap"
                elif row["Low"] <= stop:
                    exit_price, reason = stop, "trail-stop"
                else:
                    pos["peak"] = max(pos["peak"], float(row["High"]))
            else:
                stop = pos["entry"] * (1 - STOP_LOSS)
                tp   = pos["entry"] * (1 + TAKE_PROFIT)
                if op <= stop:
                    exit_price, reason = op, "stop-gap"
                elif row["Low"] <= stop:
                    exit_price, reason = stop, "stop-loss"
                elif exit_mode == "fixed" and op >= tp:
                    exit_price, reason = op, "tp-gap"
                elif exit_mode == "fixed" and row["High"] >= tp:
                    exit_price, reason = tp, "take-profit"

            if exit_price is None:
                loc = df.index.get_loc(d)
                if loc >= LOOKBACK:
                    w   = df.iloc[loc - LOOKBACK + 1: loc + 1]
                    ind = indicators(w["Close"].tolist(), w["Volume"].tolist())
                    if exit_mode == "fixed" and sum([ind["rsi"] > 70, ind["macd"] < 0,
                                                     ind["price"] < ind["vwap"]]) >= 2:
                        exit_price, reason = float(row["Close"]), "sell-signal"
                    elif exit_mode == "rsi_recover" and ind["rsi"] > 50:
                        exit_price, reason = float(row["Close"]), "rsi-recover"

            if exit_price is not None:
                cash += pos["shares"] * exit_price
                trades.append({
                    "symbol": sym, "entry_date": str(pos["entry_date"].date()),
                    "exit_date": str(d.date()),
                    "pct": round(100 * (exit_price / pos["entry"] - 1), 2),
                    "pnl": round(pos["shares"] * (exit_price - pos["entry"]), 2),
                    "reason": reason,
                })
                del positions[sym]

        # entries
        if not use_filter or spy_ok.get(d, False):
            for sym in SYMBOLS:
                if sym in positions or cash < 1:
                    continue
                df = data.get(sym)
                if df is None or d not in df.index:
                    continue
                loc = df.index.get_loc(d)
                if loc < LOOKBACK:
                    continue
                w   = df.iloc[loc - LOOKBACK + 1: loc + 1]
                ind = indicators(w["Close"].tolist(), w["Volume"].tolist())
                if entry_fn(ind):
                    dollars = min(MAX_POSITION, cash)
                    price   = float(df.loc[d, "Close"])
                    positions[sym] = {"shares": dollars / price, "entry": price,
                                      "entry_date": d, "peak": price}
                    cash -= dollars

        # mark to market
        value = cash
        for sym, pos in positions.items():
            df = data[sym]
            px = float(df.loc[d, "Close"]) if d in df.index else pos["entry"]
            value += pos["shares"] * px
        equity.append((d, value))

    return equity, trades


def stats(equity, trades, label):
    final = equity[-1][1]
    ret   = 100 * (final / TOTAL_BUDGET - 1)
    peak = mdd = 0.0
    for _, v in equity:
        peak = max(peak, v)
        mdd  = max(mdd, (peak - v) / peak if peak else 0)
    n_days = (equity[-1][0] - equity[0][0]).days
    wins   = sum(1 for t in trades if t["pnl"] > 0)
    return {
        "strategy":   label,
        "final":      round(final, 2),
        "return_pct": round(ret, 2),
        "annual_pct": round(100 * ((final / TOTAL_BUDGET) ** (365 / n_days) - 1), 2),
        "max_dd_pct": round(100 * mdd, 2),
        "trades":     len(trades),
        "win_rate":   round(100 * wins / len(trades)) if trades else None,
    }


def run():
    raw = yf.download(SYMBOLS + [BENCHMARK], period="3y", interval="1d",
                      auto_adjust=True, progress=False, group_by="ticker")
    data = {}
    for sym in SYMBOLS + [BENCHMARK]:
        df = raw[sym].dropna()
        if len(df) >= LOOKBACK + 10:
            data[sym] = df

    spy = data[BENCHMARK]
    sma = spy["Close"].rolling(REGIME_SMA).mean()
    spy_ok = {d: bool(spy["Close"].loc[d] > sma.loc[d])
              for d in spy.index if not sma.loc[d] != sma.loc[d]}

    # common start: SPY has its 50d SMA and symbols have 30 bars; align to the
    # earlier backtest window (last 2 years of trading days)
    all_dates = sorted(set().union(*(set(df.index) for df in data.values()
                                     if df is not spy)))
    start = [d for d in all_dates if d in spy_ok][0]
    two_years_ago = all_dates[-1] - __import__("pandas").Timedelta(days=730)
    dates = [d for d in all_dates if d >= max(start, two_years_ago)]

    spy_ret = 100 * (float(spy["Close"].iloc[-1]) /
                     float(spy["Close"].loc[dates[0]]) - 1)

    results = []
    all_trades = {}
    for strat in STRATEGIES:
        for use_filter in (False, True):
            label = strat + ("+filter" if use_filter else "")
            equity, trades = simulate(data, dates, spy_ok, strat, use_filter)
            results.append(stats(equity, trades, label))
            all_trades[label] = trades

    print(f"\nPeriod: {dates[0].date()} -> {dates[-1].date()}"
          f"  |  SPY buy & hold: {spy_ret:+.2f}%")
    print(f"Universe: {', '.join(s for s in SYMBOLS if s in data)}"
          f"  |  budget ${TOTAL_BUDGET:.0f}, ${MAX_POSITION:.0f}/position\n")
    hdr = f"{'strategy':18} {'final $':>9} {'return':>8} {'annual':>8} {'max DD':>8} {'trades':>7} {'win %':>6}"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        win = f"{r['win_rate']}%" if r["win_rate"] is not None else "-"
        print(f"{r['strategy']:18} {r['final']:>9.2f} {r['return_pct']:>+7.2f}% "
              f"{r['annual_pct']:>+7.2f}% {-r['max_dd_pct']:>7.2f}% {r['trades']:>7} {win:>6}")

    with open("backtest_v2_results.json", "w") as f:
        json.dump({"summary": results, "trades": all_trades}, f, indent=2)
    print("\nFull trade logs written to backtest_v2_results.json")


if __name__ == "__main__":
    run()
