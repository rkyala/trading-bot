"""
PEAD (post-earnings announcement drift) backtest on the Nasdaq-100.

Rule under test: when a stock GAPS UP at the open on its post-earnings
reaction day (the market liked the report), buy at that open and ride the
drift. No prediction of results — the market grades the earnings overnight,
we trade the morning after.

Two layers of evidence:
  1. Event study — across all reaction days, did gap-ups keep drifting?
  2. Portfolio sim — $500 budget, $125/position, max 4 concurrent, entry at
     the open, exit via trailing stop (gap-aware fills, stop-first).
"""

import json
import os
import time

import pandas as pd
import yfinance as yf

TICKERS    = json.load(open("n100_tickers.json"))
CACHE      = "earnings_dates.json"
PERIOD     = "3y"
GAP_THRESH = [0.03, 0.05, 0.08]
TRAIL_PCT  = 0.05
STOP_LOSS  = 0.03
MAX_POS    = 125.0
BUDGET     = 500.0


def load_earnings_dates():
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    out = {}
    for i, sym in enumerate(TICKERS):
        try:
            ed = yf.Ticker(sym).get_earnings_dates(limit=16)
            if ed is not None and len(ed):
                out[sym] = [str(ts) for ts in ed.index]
        except Exception as exc:
            print(f"  {sym}: earnings dates failed ({exc})")
        if i % 20 == 19:
            print(f"  ...{i + 1}/{len(TICKERS)} tickers")
        time.sleep(0.15)
    json.dump(out, open(CACHE, "w"))
    return out


def reaction_day(df, ts):
    """Trading day whose open reflects the earnings report."""
    d = pd.Timestamp(ts).tz_localize(None)
    after_close = d.hour >= 12        # AMC report -> next trading day's open
    day = d.normalize()
    idx = df.index.tz_localize(None).normalize()
    later = [i for i, x in enumerate(idx) if x > day] if after_close else \
            [i for i, x in enumerate(idx) if x >= day]
    return later[0] if later else None


def run():
    print("Loading earnings dates (cached after first run)...")
    edates = load_earnings_dates()
    print(f"{len(edates)} tickers with earnings dates")

    raw = yf.download(TICKERS, period=PERIOD, interval="1d", auto_adjust=True,
                      progress=False, group_by="ticker", threads=True)
    data = {}
    for sym in TICKERS:
        try:
            df = raw[sym].dropna()
        except (KeyError, IndexError):
            continue
        if len(df) > 60:
            data[sym] = df

    # ── build events ─────────────────────────────────────────────────────────
    events = []  # (date, sym, row_index, gap)
    for sym, dates in edates.items():
        df = data.get(sym)
        if df is None:
            continue
        for ts in dates:
            i = reaction_day(df, ts)
            if i is None or i < 1 or i >= len(df):
                continue
            gap = float(df["Open"].iloc[i] / df["Close"].iloc[i - 1] - 1)
            events.append((df.index[i], sym, i, gap))
    # de-dup (same event can appear from multiple date entries)
    events = sorted({(d, s): (d, s, i, g) for d, s, i, g in events}.values())
    print(f"{len(events)} unique post-earnings reaction days "
          f"({min(e[0] for e in events).date()} -> {max(e[0] for e in events).date()})\n")

    # ── 1. event study ───────────────────────────────────────────────────────
    print("EVENT STUDY — buy the open of the reaction day, gap-up events only")
    hdr = (f"{'gap >=':>7} {'events':>7} {'day0%':>7} {'+5d%':>7} {'+10d%':>7} "
           f"{'win5d':>6} {'win10d':>7}")
    print(hdr); print("-" * len(hdr))
    for th in GAP_THRESH:
        d0, r5, r10 = [], [], []
        for _, sym, i, gap in events:
            if gap < th:
                continue
            df = data[sym]
            o = float(df["Open"].iloc[i])
            d0.append(float(df["Close"].iloc[i]) / o - 1)
            if i + 4 < len(df):
                r5.append(float(df["Close"].iloc[i + 4]) / o - 1)
            if i + 9 < len(df):
                r10.append(float(df["Close"].iloc[i + 9]) / o - 1)
        if not d0:
            continue
        avg = lambda xs: 100 * sum(xs) / len(xs) if xs else float("nan")
        win = lambda xs: 100 * sum(1 for x in xs if x > 0) / len(xs) if xs else 0
        print(f"{100*th:>6.0f}% {len(d0):>7} {avg(d0):>+7.2f} {avg(r5):>+7.2f} "
              f"{avg(r10):>+7.2f} {win(r5):>5.0f}% {win(r10):>6.0f}%")

    # control: ALL reaction days regardless of gap (does drift need the gap?)
    r5_all = []
    for _, sym, i, gap in events:
        df = data[sym]
        if i + 4 < len(df):
            r5_all.append(float(df["Close"].iloc[i + 4]) / float(df["Open"].iloc[i]) - 1)
    print(f"{'any':>7} {len(r5_all):>7} {'':>7} "
          f"{100*sum(r5_all)/len(r5_all):>+7.2f} {'':>7} "
          f"{100*sum(1 for x in r5_all if x>0)/len(r5_all):>5.0f}%")

    # ── 2. portfolio simulation (gap >= 5%, trailing stop) ───────────────────
    print("\nPORTFOLIO SIM — gap>=5%, buy open, -3% stop trailing 5% below peak")
    by_day = {}
    for d, sym, i, gap in events:
        if gap >= 0.05:
            by_day.setdefault(d, []).append((sym, i, gap))

    all_days = sorted(set().union(*(set(df.index) for df in data.values())))
    cash, positions, trades = BUDGET, {}, []
    equity = []
    for d in all_days:
        # exits
        for sym in list(positions):
            df, pos = data[sym], positions[sym]
            if d not in df.index:
                continue
            row = df.loc[d]
            op = float(row["Open"])
            stop = max(pos["entry"] * (1 - STOP_LOSS), pos["peak"] * (1 - TRAIL_PCT))
            px = None
            if op <= stop:
                px = op
            elif float(row["Low"]) <= stop:
                px = stop
            else:
                pos["peak"] = max(pos["peak"], float(row["High"]))
            if px is not None:
                cash += pos["shares"] * px
                trades.append({"symbol": sym, "entry_date": str(pos["date"].date()),
                               "exit_date": str(d.date()),
                               "pct": round(100 * (px / pos["entry"] - 1), 2),
                               "pnl": round(pos["shares"] * (px - pos["entry"]), 2)})
                del positions[sym]
        # entries at the open of reaction days
        for sym, i, gap in sorted(by_day.get(d, []), key=lambda x: -x[2]):
            if sym in positions or cash < 1:
                continue
            o = float(data[sym]["Open"].iloc[i])
            dollars = min(MAX_POS, cash)
            positions[sym] = {"shares": dollars / o, "entry": o, "peak": o, "date": d}
            cash -= dollars
        # mark
        v = cash
        for sym, pos in positions.items():
            df = data[sym]
            v += pos["shares"] * (float(df.loc[d, "Close"]) if d in df.index else pos["entry"])
        equity.append((d, v))

    final = equity[-1][1]
    peak = mdd = 0.0
    for _, v in equity:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak else 0)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    days = (equity[-1][0] - equity[0][0]).days
    print(f"start ${BUDGET:.0f} -> final ${final:.2f}  "
          f"({100*(final/BUDGET-1):+.2f}% total, "
          f"{100*((final/BUDGET)**(365/days)-1):+.2f}%/yr)")
    print(f"max drawdown -{100*mdd:.2f}%  |  trades {len(trades)}  |  "
          f"win rate {100*wins/len(trades):.0f}%" if trades else "no trades")
    trades.sort(key=lambda t: t["pnl"])
    print("worst:", trades[:3])
    print("best :", trades[-3:])
    json.dump({"trades": trades, "final": final},
              open("backtest_pead_results.json", "w"), indent=2)


if __name__ == "__main__":
    run()
