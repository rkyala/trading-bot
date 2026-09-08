"""
Continuous Technical Gate Scoring (replaces coarse pass/marginal/fail buckets)

PROBLEM (measured Sep 8 on the live equity run):
    Gate 9  MA20 : 7 pass / 1 marginal / 1 fail
    Gate 10 RSI  : 7 pass / 1 marginal / 1 fail
    Gate 11 VWAP : 4 pass / 5 marginal / 0 fail
    Confidence actually assigned: only 90%, 96%, 100%
    Trades blocked on low confidence: 0

The old formula was `0.75 baseline + per-gate nudge`, where a pass added about
+0.09 and a "marginal" +0.04. Three marginal gates still landed at ~0.87 — full
size. It took two hard failures to fall under the 0.50 floor. The gates were
scoring, but not discriminating.

THIS MODULE:
  1. Scores each gate CONTINUOUSLY in [0,1] instead of three buckets.
  2. Normalises distances by ATR, so "above MA20" means the same thing on a
     $19 stock and a $1,700 stock.
  3. Combines by WEIGHTED MEAN with no baseline — the score has no opinion
     until the evidence arrives, rather than starting at 0.75.
  4. Adds HARD VETOES for setups that should never trade regardless of the
     other gates (buying strength far below its own trend, blow-off RSI).
"""

import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

# Weights sum to 1.0. Trend gets the most weight; momentum and location split
# the rest. VWAP is the weakest signal of the three (it never once failed in
# live observation, so it carries little information on its own).
WEIGHT_MA = 0.40
WEIGHT_RSI = 0.35
WEIGHT_VWAP = 0.25

VETO = 0.0


def _interp(x: float, points) -> float:
    """Piecewise-linear interpolation over sorted (x, y) points."""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


def score_ma(price: float, ma20: float, atr: float, is_bullish: bool) -> Tuple[float, str]:
    """
    Trend alignment, measured in ATR units above/below MA20.

    Using ATR units rather than percent keeps the gate comparable across names:
    $2 above MA20 is decisive on a low-volatility stock and noise on TSLA.
    """
    if not ma20 or ma20 <= 0 or not atr or atr <= 0:
        return 0.50, "no MA/ATR data — neutral"

    z = (price - ma20) / atr
    if not is_bullish:
        z = -z  # for a bearish position, below the MA is the favourable side

    # Hard veto: taking a directional position more than 1.5 ATR against its
    # own trend. This is the single most reliable way to lose on flow signals.
    if z < -1.5:
        return VETO, f"VETO: {abs(z):.1f} ATR against trend"

    score = _interp(z, [(-1.5, 0.05), (-0.5, 0.25), (0.0, 0.50),
                        (0.5, 0.80), (1.5, 1.00), (3.0, 0.75), (5.0, 0.55)])

    # Report the RAW position, not the direction-normalised one. `z` above is
    # sign-flipped for bearish setups so the scoring curve can be shared, but
    # logging that flipped value reads as its opposite: a put 1.35 ATR BELOW
    # its MA20 was printing "+1.35 ATR vs MA20", which looks like an uptrend.
    raw_z = (price - ma20) / atr
    side = "above" if raw_z >= 0 else "below"
    fav = "favourable" if z >= 0 else "against"
    return score, f"{abs(raw_z):.2f} ATR {side} MA20 ({fav})"


def score_rsi(rsi: float, is_bullish: bool) -> Tuple[float, str]:
    """
    Momentum. Rewards the middle of the range; punishes exhaustion.

    For a long we want RSI with room to run (45-65), not a blow-off top.
    """
    if rsi is None:
        return 0.50, "no RSI — neutral"

    r = rsi if is_bullish else 100.0 - rsi  # mirror the curve for shorts

    if r >= 85:
        return VETO, f"VETO: RSI {rsi:.0f} exhausted"
    if r <= 15:
        return VETO, f"VETO: RSI {rsi:.0f} capitulation"

    # Peak sits at 55-65: momentum CONFIRMED but not exhausted. RSI 50 means
    # no momentum in either direction, so it scores well but not perfectly —
    # an earlier curve peaked at 50 and let flat setups score like ideal ones.
    score = _interp(r, [(15, 0.05), (30, 0.35), (40, 0.62), (50, 0.82),
                        (58, 1.00), (66, 0.95), (72, 0.60), (78, 0.30), (85, 0.05)])
    return score, f"RSI {rsi:.1f}"


def score_vwap(price: float, vwap: float, atr: float, is_bullish: bool) -> Tuple[float, str]:
    """
    Location vs the session's volume-weighted average — i.e. whether today's
    buyers are in profit. Normalised by ATR like the MA gate.
    """
    if not vwap or vwap <= 0 or not atr or atr <= 0:
        return 0.50, "no VWAP/ATR data — neutral"

    z = (price - vwap) / atr
    if not is_bullish:
        z = -z

    score = _interp(z, [(-1.0, 0.10), (-0.3, 0.35), (0.0, 0.55),
                        (0.3, 0.85), (1.0, 1.00), (2.5, 0.80)])

    raw_z = (price - vwap) / atr
    side = "above" if raw_z >= 0 else "below"
    fav = "favourable" if z >= 0 else "against"
    return score, f"{abs(raw_z):.2f} ATR {side} VWAP ({fav})"


def combine(ma: float, rsi: float, vwap: float) -> float:
    """
    Weighted mean, no baseline. Any hard veto collapses the whole score.

    The old scheme started every candidate at 0.75 and nudged; this starts from
    the evidence, so weak setups genuinely land low.
    """
    if VETO in (ma, rsi, vwap):
        return 0.0
    return round(WEIGHT_MA * ma + WEIGHT_RSI * rsi + WEIGHT_VWAP * vwap, 4)


def score_all(
    price: float,
    ma20: Optional[float],
    rsi: Optional[float],
    vwap: Optional[float],
    atr: Optional[float],
    is_bullish: bool,
) -> Dict:
    """Score all three gates and combine. Returns detail for logging."""
    s_ma, r_ma = score_ma(price, ma20, atr, is_bullish)
    s_rsi, r_rsi = score_rsi(rsi, is_bullish)
    s_vwap, r_vwap = score_vwap(price, vwap, atr, is_bullish)

    confidence = combine(s_ma, s_rsi, s_vwap)
    vetoed = confidence == 0.0

    return {
        "confidence": confidence,
        "vetoed": vetoed,
        "ma": {"score": s_ma, "reason": r_ma},
        "rsi": {"score": s_rsi, "reason": r_rsi},
        "vwap": {"score": s_vwap, "reason": r_vwap},
    }
