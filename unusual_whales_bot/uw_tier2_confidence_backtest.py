#!/usr/bin/env python3
"""
Does Tier 2's confidence number predict whether its exit was a good one?

THE QUESTION
Tier 2 computes a confidence for every exit signal, logs it, and (until
Sep 10 2026) consumed it nowhere. Before a confidence FLOOR can be sited at
any particular value, confidence has to actually rank exit quality: high
confidence exits should beat low confidence exits. This measures that.

THE COMPARISON
For each position that both (a) received at least one shadow signal and
(b) has since closed:

    hypothetical  = return at the FIRST signal clearing threshold C
    actual        = the return the position really achieved
    delta         = hypothetical - actual

delta > 0 means acting on Tier 2 at that threshold would have beaten what the
bot really did. Sweeping C then shows whether a higher bar produces better
exits, which is the only thing that would justify setting the floor above 0.

THE BAR, DECLARED BEFORE THE RUN
  * mean delta must be positive AND |t| >= 2 at some threshold, AND
  * the effect must be MONOTONE-ish in C - higher floors giving better deltas.
A single threshold spiking while its neighbours sit at zero is what a sweep
over a small sample produces by chance, not an edge.

WHY THIS IS EXPECTED TO FAIL ON POWER, NOT ON MERIT
The sample is tiny. Every closed position that ever drew a signal is n<=20 at
the time of writing. Sweeping ~10 thresholds over 18 points is a
multiple-comparisons machine of exactly the kind that produced this project's
earlier false positives (a Sharpe 33 condor, an SPY t+2.19 that evaporated
out of sample). The sample size is therefore printed BEFORE the table, and
the verdict refuses to call an edge below MIN_N regardless of what the
numbers say.

NO LOOK-AHEAD
Only signals logged strictly BEFORE the position's exit_time are eligible.
A signal recorded after the position closed is not a decision anyone could
have acted on.
"""

import json
import math
import os
import statistics as st
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADOW = os.path.join(REPO, "tier2_shadow.jsonl")
CLOSED = os.path.join(REPO, "closed_trades.jsonl")

# Declared in advance.
THRESHOLDS = [0.0, 0.30, 0.40, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
MIN_N = 30          # below this, report as underpowered no matter the t-stat


def _load(path):
    out = []
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return out


def build_pairs():
    """Match shadow signals to closed outcomes by candidate_id."""
    shadow = _load(SHADOW)
    closed = _load(CLOSED)

    by_cand = {}
    for c in closed:
        cid = c.get("candidate_id")
        if cid and c.get("pnl_pct") is not None:
            by_cand[cid] = c

    sigs = {}
    for s in shadow:
        cid = s.get("candidate_id")
        if cid in by_cand and s.get("return_at_signal_pct") is not None:
            sigs.setdefault(cid, []).append(s)

    pairs = []
    for cid, ss in sigs.items():
        c = by_cand[cid]
        exit_time = str(c.get("exit_time") or "")
        # Signals must predate the exit; anything after is not actionable.
        ss = [s for s in ss if str(s.get("logged_at") or "") < exit_time] if exit_time else ss
        if not ss:
            continue
        ss.sort(key=lambda s: str(s.get("logged_at") or ""))
        pairs.append({
            "cid": cid,
            "symbol": c.get("symbol"),
            "actual": float(c["pnl_pct"]),
            "signals": ss,
            "exit_reason": c.get("exit_reason"),
        })
    return pairs, len(closed), len(shadow)


def evaluate(pairs, thresh):
    """Return deltas for positions that produce a signal at or above thresh."""
    deltas = []
    for p in pairs:
        hit = next((s for s in p["signals"] if float(s["confidence"]) >= thresh), None)
        if hit is None:
            continue                       # gate would never have fired: hold
        deltas.append(float(hit["return_at_signal_pct"]) - p["actual"])
    return deltas


def main():
    pairs, n_closed, n_shadow = build_pairs()

    print("=" * 88)
    print("TIER 2 CONFIDENCE GATE — does confidence rank exit quality?")
    print("=" * 88)
    print(f"  shadow signals: {n_shadow}   closed trades: {n_closed}")
    print(f"  MATCHED SAMPLE: {len(pairs)} positions")
    print()
    if len(pairs) < MIN_N:
        print(f"  *** n = {len(pairs)} is below the MIN_N = {MIN_N} declared before this run.")
        print("  *** Whatever the table shows, it cannot site a threshold. Sweeping")
        print(f"  *** {len(THRESHOLDS)} thresholds over {len(pairs)} points will produce an apparent")
        print("  *** winner by chance alone. Read the numbers as descriptive only.")
        print()

    if not pairs:
        print("  no matched positions - nothing to measure")
        return 1

    print(f"  {'floor':>7}{'n fired':>9}{'mean delta':>13}{'t':>8}{'better':>9}{'median':>10}")
    print("  " + "-" * 56)
    rows = []
    for c in THRESHOLDS:
        d = evaluate(pairs, c)
        if not d:
            print(f"  {c:>7.2f}{0:>9}{'-':>13}{'-':>8}{'-':>9}{'-':>10}")
            continue
        n = len(d)
        mean = st.mean(d)
        sd = st.pstdev(d) if n > 1 else 0.0
        t = mean / (sd / math.sqrt(n)) if sd else 0.0
        better = sum(1 for x in d if x > 0) / n * 100
        print(f"  {c:>7.2f}{n:>9}{mean:>+13.3f}{t:>+8.2f}{better:>8.0f}%{st.median(d):>+10.3f}")
        rows.append((c, n, mean, t))
    print("  " + "-" * 56)
    print("  delta = (return if Tier 2 exited at signal) - (return actually achieved)")
    print("  positive => acting on Tier 2 at that floor would have been better")
    print()

    # Pre-declared bar.
    sig = [r for r in rows if r[2] > 0 and abs(r[3]) >= 2.0]
    print("  BAR DECLARED BEFORE THE RUN:")
    print("    (1) some floor with mean delta > 0 and |t| >= 2")
    print(f"    (2) effect roughly monotone in the floor")
    print(f"    (3) n >= {MIN_N}")
    print(f"      (1) thresholds clearing: {len(sig)}")
    print(f"      (3) n = {len(pairs)}  -> {'OK' if len(pairs) >= MIN_N else 'FAILS'}")
    print()
    if len(pairs) < MIN_N:
        verdict = "UNDERPOWERED - cannot site a floor; keep tier2_min_exit_confidence at 0.0"
    elif sig:
        verdict = "candidate - inspect monotonicity before trusting"
    else:
        verdict = "NULL - confidence does not rank exit quality"
    print(f"  VERDICT: {verdict}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
