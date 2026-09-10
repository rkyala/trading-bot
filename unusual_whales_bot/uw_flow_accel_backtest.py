#!/usr/bin/env python3
"""
Flow ACCELERATION, read against the dealer-gamma regime.

WHY THIS IS NOT THE TEST THAT ALREADY FAILED
The flow hypothesis we nulled measured the LEVEL of directional flow:
(bullish-bearish)/(bullish+bearish) over a window, forward return <=0.03%/day,
hit rate 47-53%. This measures the SECOND derivative - the rate of change of
the cumulative net-premium line - which is a different feature and untested.

More importantly it is tested CONDITIONALLY. The mechanism:

    long gamma   dealers hedge AGAINST price, so incoming flow is absorbed
                 and the move mean-reverts
    short gamma  dealers hedge WITH price, so flow is amplified and the move
                 extends

Same flow, opposite read. If that is true, an UNCONDITIONAL test blends two
opposite-signed populations and returns a null even when both halves are
real - which is a candidate explanation for why the level test washed out.

So the headline is the INTERACTION, not either regime alone:

    interaction = mean signed return (short gamma) - mean signed return (long gamma)

DATA (all three verified historical; date honoured in the payload)
  /stock/{t}/net-prem-ticks?date=D   405 minute rows, net_call_premium,
      net_put_premium, ask/bid side splits, net_delta. Mids stripped and each
      trade capped at $2M by UW before it reaches us.
  /stock/{t}/ohlc/1m?date=D          minute bars for the forward return
  /stock/{t}/greek-exposure/strike?date=D-1   regime, from the PREVIOUS
      session so it is knowable intraday on D. gamma_flip is skipped - it is
      frequently null; the sign of summed net gex off the ladder is used.

GUARDS, all of them bought with earlier false positives on this project
  non-overlapping events - a HOLD-minute hold with overlapping entries
      inflates t by roughly sqrt(HOLD); events are spaced >= HOLD apart
  market-adjusted - returns are excess over SPY over the same minutes, or an
      intraday flow signal mostly measures beta
  winsorised at 1/99 so a single minute cannot carry a ticker
  open/close excluded - the first and last 15 minutes are their own regime
  per-ticker sign criterion - the GEX barrier test passed POOLED at t+1.98
      while AMD alone was 70% of the effect. Pooling correlated names inflates
      t. A result that does not hold on a majority of tickers is not a result.

THE BAR, DECLARED BEFORE THE RUN
  1. interaction > 0 with |t| >= 2
  2. majority of tickers show a positive interaction
  3. at least one regime individually reaches |t| >= 2
All three, or it is a null.

RESULT — FAILS ALL THREE. 12 tickers, 456 ticker-days, 3,251 events.

    regime           n     mean %       t    hit%
    ALL           3251    -0.0001   -0.02   49.5%
    short gamma    737    -0.0035   -0.37   49.0%
    long gamma    2514    +0.0017   +0.29   49.6%

    INTERACTION (short - long): -0.0052%   t -0.46
    (1) FAIL (t=-0.46)   (2) FAIL (3/7)   (3) FAIL

Not an underpowered "cannot tell" - 3,251 non-overlapping events is enough
to say this is flat. Three details worth keeping:

  the interaction has the WRONG SIGN. The mechanism predicts short-gamma
    extension minus long-gamma absorption should be POSITIVE; it is negative.
    Noise, but not noise leaning the predicted way.
  hit rates are 49.0 / 49.6 / 49.5% - coin flips in BOTH regimes.
  effect sizes are ~0.5 basis points, an order of magnitude inside the spread
    on these names. Untradeable even if real.

WHAT THIS CLOSES
The conditional framing was the strongest surviving explanation for why the
original flow test nulled - that flow works in both directions and an
unconditional test averages them to zero. That explanation is now tested and
does not hold. Flow -> direction is dead at the LEVEL and at the
ACCELERATION, CONDITIONED and UNCONDITIONED.

INCIDENTAL, worth knowing before designing anything else on this split
Long gamma dominates 77% of ticker-days (2,514 vs 737), so the short-gamma
arm is always the sample-starved half. Five of twelve tickers came back too
thin to compute both arms at all.
"""

import argparse
import math
import os
import statistics as st
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

BASE = "https://api.unusualwhales.com/api"

FAST = 5          # minutes in the fast flow window
HOLD = 15         # minutes held after an event
Z_TRIGGER = 1.5   # acceleration z-score that counts as an event
SKIP_EDGE = 15    # minutes excluded at each end of the session
MARKET_REF = "SPY"  # excluded from the universe: it IS the adjustment


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def winsorise(xs: List[float]) -> List[float]:
    if len(xs) < 20:
        return xs
    s = sorted(xs)
    lo, hi = s[int(len(s) * 0.01)], s[int(len(s) * 0.99)]
    return [min(max(x, lo), hi) for x in xs]


class FlowAccel:
    def __init__(self):
        import requests
        self.s = requests.Session()
        key = os.getenv("UW_API_KEY")
        if key:
            self.s.headers.update({"Authorization": f"Bearer {key}",
                                   "Accept": "application/json"})
        self.stats = {"days": 0, "no_flow": 0, "no_px": 0, "no_gex": 0, "events": 0}
        self._spy: Dict[str, Dict[str, float]] = {}

    def _get(self, path: str, params: Dict) -> List[Dict]:
        import time as _t
        for a in range(3):
            try:
                r = self.s.get(f"{BASE}{path}", params=params, timeout=30)
                if r.status_code == 200:
                    return r.json().get("data") or []
                if r.status_code == 429:
                    _t.sleep(2 * (a + 1))
                    continue
                return []
            except Exception:
                _t.sleep(1)
        return []

    # ------------------------------------------------------------------ data

    def minute_px(self, ticker: str, day: str) -> Dict[str, float]:
        """close keyed by HH:MM, regular session only."""
        rows = self._get(f"/stock/{ticker}/ohlc/1m", {"date": day, "limit": 1000})
        out = {}
        for r in rows:
            if str(r.get("market_time") or "") != "r":
                continue
            t = str(r.get("start_time") or "")
            c = _f(r.get("close"))
            if len(t) >= 16 and c and c > 0:
                out[t[11:16]] = c
        return out

    def flow(self, ticker: str, day: str) -> List[Tuple[str, float]]:
        """(HH:MM, directional net premium) — positive is net call buying."""
        rows = self._get(f"/stock/{ticker}/net-prem-ticks", {"date": day})
        if not rows or str(rows[0].get("date") or "")[:10] != day:
            return []
        out = []
        for r in rows:
            t = str(r.get("tape_time") or "")
            if len(t) < 16:
                continue
            ncp = _f(r.get("net_call_premium"), 0.0) or 0.0
            npp = _f(r.get("net_put_premium"), 0.0) or 0.0
            # net_call_premium is ask-side minus bid-side call premium, so it
            # is already signed for aggressor. Bullish = calls bought AND puts
            # sold, hence the subtraction rather than a sum.
            out.append((t[11:16], ncp - npp))
        out.sort()
        return out

    def gamma_sign(self, ticker: str, day: str) -> Optional[float]:
        rows = self._get(f"/stock/{ticker}/greek-exposure/strike", {"date": day})
        if not rows or str(rows[0].get("date") or "")[:10] != day:
            return None
        net = 0.0
        for r in rows:
            net += (_f(r.get("call_gex"), 0.0) or 0.0) + (_f(r.get("put_gex"), 0.0) or 0.0)
        return net

    def spy_px(self, day: str) -> Dict[str, float]:
        if day not in self._spy:
            self._spy[day] = self.minute_px("SPY", day)
        return self._spy[day]

    # ------------------------------------------------------------- signal

    @staticmethod
    def events(flow: List[Tuple[str, float]]) -> List[Tuple[str, float]]:
        """
        (minute, acceleration z) for every minute with enough history.

        Acceleration is the change in the FAST-minute flow rate: the current
        FAST-minute sum minus the preceding FAST-minute sum. That is the rate
        of change of the cumulative line, sampled per minute.
        """
        vals = [v for _, v in flow]
        mins = [m for m, _ in flow]
        out = []
        roll = []
        for i in range(len(vals)):
            if i < 2 * FAST:
                continue
            cur = sum(vals[i - FAST + 1:i + 1])
            prev = sum(vals[i - 2 * FAST + 1:i - FAST + 1])
            roll.append((mins[i], cur - prev))
        if len(roll) < 30:
            return []
        accs = [a for _, a in roll]
        sd = st.pstdev(accs)
        if sd <= 0:
            return []
        mu = st.mean(accs)
        return [(m, (a - mu) / sd) for m, a in roll]

    # ---------------------------------------------------------------- run

    def run_day(self, ticker: str, day: str, prev_day: str) -> List[Dict]:
        # The market reference cannot be market-adjusted against itself: every
        # signed return comes out EXACTLY 0.0, and those zeros then sit inside
        # whichever gamma regime SPY happened to be in, dragging that regime's
        # mean toward zero and its hit rate to 0%. Caught in a smoke test where
        # short gamma read mean +0.0000, t +0.00, hit 0.0% over 17 events.
        if ticker == MARKET_REF:
            return []
        fl = self.flow(ticker, day)
        if not fl:
            self.stats["no_flow"] += 1
            return []
        px = self.minute_px(ticker, day)
        if len(px) < 200:
            self.stats["no_px"] += 1
            return []
        g = self.gamma_sign(ticker, prev_day)
        if g is None:
            self.stats["no_gex"] += 1
            return []
        spy = self.spy_px(day)
        if len(spy) < 200:
            return []
        self.stats["days"] += 1

        mins = sorted(px)
        pos = {m: i for i, m in enumerate(mins)}
        rows, last_i = [], -10 ** 9

        for m, z in self.events(fl):
            if abs(z) < Z_TRIGGER or m not in pos:
                continue
            i = pos[m]
            # Exclude the open and close, and require a full holding window.
            if i < SKIP_EDGE or i + HOLD >= len(mins) - SKIP_EDGE:
                continue
            # NON-OVERLAPPING: overlapping holds inflate t by ~sqrt(HOLD).
            if i - last_i < HOLD:
                continue
            m2 = mins[i + HOLD]
            if m not in spy or m2 not in spy:
                continue
            r = (px[m2] / px[m] - 1.0) * 100
            rs = (spy[m2] / spy[m] - 1.0) * 100
            signed = math.copysign(1.0, z) * (r - rs)      # market-adjusted
            rows.append({"ticker": ticker, "day": day, "min": m, "z": z,
                         "signed": signed, "regime": "short" if g < 0 else "long"})
            last_i = i
            self.stats["events"] += 1
        return rows


def block(rows: List[Dict], regime: Optional[str] = None) -> Dict:
    r = [x for x in rows if regime is None or x["regime"] == regime]
    if len(r) < 10:
        return {}
    v = winsorise([x["signed"] for x in r])
    n = len(v)
    sd = st.pstdev(v)
    return {"n": n, "mean": st.mean(v),
            "t": st.mean(v) / (sd / math.sqrt(n)) if sd else 0.0,
            "hit": sum(1 for x in v if x > 0) / n * 100}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="QQQ,AAPL,NVDA,TSLA,META,AMD,MSFT,AMZN,GOOGL,NFLX")
    ap.add_argument("--days", type=int, default=25)
    a = ap.parse_args()

    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    bt = FlowAccel()

    today = date.today()
    sess, i = [], 1
    while len(sess) < a.days + 1 and i < a.days * 2 + 40:
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            sess.append(d.isoformat())
        i += 1
    sess.sort()

    print("=" * 96)
    print("FLOW ACCELERATION x GAMMA REGIME")
    print("=" * 96)
    print(f"  accel = d/dt of cumulative net premium ({FAST}m rate change) | "
          f"trigger |z|>={Z_TRIGGER} | hold {HOLD}m")
    print(f"  market-adjusted vs SPY | non-overlapping | winsorised 1/99 | "
          f"regime from PREVIOUS session")
    print()

    allrows, per_ticker = [], {}
    for t in tickers:
        tr = []
        for n in range(1, len(sess)):
            tr += bt.run_day(t, sess[n], sess[n - 1])
        if tr:
            allrows += tr
            per_ticker[t] = tr
        print(f"  {t:<6} {len(tr):>5} events")
    print(f"\n  fetch: {bt.stats}")
    if not allrows:
        print("  no data")
        return 1

    print()
    print(f"  {'regime':<14}{'n':>7}{'mean %':>10}{'t':>8}{'hit%':>8}")
    print("  " + "-" * 47)
    res = {}
    for lab, reg in (("ALL", None), ("short gamma", "short"), ("long gamma", "long")):
        s = block(allrows, reg)
        res[lab] = s
        if s:
            print(f"  {lab:<14}{s['n']:>7}{s['mean']:>+10.4f}{s['t']:>+8.2f}{s['hit']:>7.1f}%")
        else:
            print(f"  {lab:<14}{'insufficient':>7}")
    print("  " + "-" * 47)
    print("  signed return: + means price CONTINUED in the direction of the")
    print("  acceleration. Hypothesis: positive in short gamma, negative in long.")

    # The interaction is the actual test.
    sh = [x["signed"] for x in allrows if x["regime"] == "short"]
    ln = [x["signed"] for x in allrows if x["regime"] == "long"]
    inter, ti = 0.0, 0.0
    if len(sh) >= 10 and len(ln) >= 10:
        sh, ln = winsorise(sh), winsorise(ln)
        inter = st.mean(sh) - st.mean(ln)
        se = math.sqrt(st.pvariance(sh) / len(sh) + st.pvariance(ln) / len(ln))
        ti = inter / se if se else 0.0
        print()
        print(f"  INTERACTION (short - long): {inter:+.4f}%  t {ti:+.2f}"
              f"   [n {len(sh)} / {len(ln)}]")

    print()
    print(f"  {'ticker':<8}{'short':>10}{'long':>10}{'interaction':>13}{'n':>7}")
    print("  " + "-" * 48)
    wins, tot = 0, 0
    for t, r in per_ticker.items():
        bs, bl = block(r, "short"), block(r, "long")
        if not bs or not bl:
            print(f"  {t:<8}{'—':>10}{'—':>10}{'thin':>13}{len(r):>7}")
            continue
        tot += 1
        d = bs["mean"] - bl["mean"]
        wins += 1 if d > 0 else 0
        print(f"  {t:<8}{bs['mean']:>+10.4f}{bl['mean']:>+10.4f}{d:>+13.4f}{len(r):>7}")
    print("  " + "-" * 48)

    ok1 = inter > 0 and abs(ti) >= 2.0
    ok2 = tot > 0 and wins > tot / 2
    ok3 = any(res.get(k) and abs(res[k]["t"]) >= 2.0 for k in ("short gamma", "long gamma"))
    print()
    print("  BAR DECLARED BEFORE THE RUN:")
    print(f"    (1) interaction > 0 and |t| >= 2:   {'PASS' if ok1 else 'FAIL'}  (t={ti:+.2f})")
    print(f"    (2) majority of tickers positive:   {'PASS' if ok2 else 'FAIL'}  ({wins}/{tot})")
    print(f"    (3) a regime individually |t| >= 2: {'PASS' if ok3 else 'FAIL'}")
    print()
    print(f"  VERDICT: {'PASSES - worth pursuing' if (ok1 and ok2 and ok3) else 'FAILS'}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
