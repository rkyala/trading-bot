#!/usr/bin/env python3
"""
Options Confirmation Layer — UW options data as a confirmation filter on the
production technical bot's entry decisions.

WHAT THIS IS
The production bot generates BUY decisions with a confidence score. This module
takes (symbol, direction, confidence) and returns an options-derived opinion:
does institutional option positioning agree with this trade?

It does NOT generate trades. It never places orders. It never touches the
locked MCP execution path, OAuth or token refresh.

READ THIS BEFORE TRUSTING IT
Measured over 192 trading days and 10,099 large blocks, UW options flow has NO
standalone directional edge: excess return bounded at <=0.03%/day, hit rates
47-53% on every cut. Three separate false positives had to be removed to reach
that conclusion (beta contamination, an unadjusted stock split, and
multiple-comparison noise).

That measured a PRIMARY signal. Using flow as a CONFIRMATION filter on top of
an independent technical signal is a different question and is genuinely
untested — a signal with zero unconditional edge can still carry conditional
information, though the prior is not favourable.

Therefore this ships in SHADOW MODE. It logs the opinion it would have acted
on and changes nothing. After enough paired observations the A/B log answers
the question with data instead of hope. Flipping SHADOW off before that log
says the layer helps would repeat the exact mistake this project has already
made several times.

TWO KINDS OF OUTPUT, AND ONLY ONE IS EVIDENCE-BASED
  directional score   from order-flow aggressor imbalance. This is the
                      untested part. It is what the confirmation filter is
                      for, and it is on probation.
  expected_move_mult  from dealer gamma. This IS measured: SPY's next-day
                      move ran 0.53% at the most positive gamma vs 0.87% at
                      the most negative, and the effect survived controlling
                      for trailing realised volatility (t+2.9). Gamma predicts
                      MAGNITUDE, not direction, so it deliberately does not
                      touch the directional score — it scales stop width and
                      position size, where a magnitude forecast belongs.

FAIL-OPEN
If UW is unreachable, slow, or returns nothing, `available` is False, the score
is 0, and the caller must proceed exactly as it would have without this module.
A confirmation layer that can halt the production bot is a liability, not a
feature. Nothing here raises.
"""

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

BASE = "https://api.unusualwhales.com/api"
AB_LOG = os.getenv("UW_CONFIRM_LOG", "uw_confirmation_ab.jsonl")

# Shadow mode: compute and log, never alter the caller's decision.
# Do not change this default until the A/B log shows the layer adds value.
SHADOW_DEFAULT = True

# Directional component weights. Gamma is absent by design (see docstring).
W_TAPE = 0.55        # today's aggregate aggressor imbalance
W_OPENING = 0.35     # opening single-leg block/sweep premium
W_IV = 0.10          # IV rank as mild crowding context

CONFIRM_AT = 25.0    # score above this = agrees
CONTRADICT_AT = -25.0

# --- calibration, set from the observed cross-section (25 large-cap names) ---
# tape ratio      median -0.0120, sd 0.0142   -> ~2 sd maps to +-85
# opening ratio   median -0.0184, sd 0.1368   -> ~2 sd maps to +-82
MARKET_REF = "SPY"          # tape readings are scored relative to this
TAPE_SCALE = 3000.0
OPENING_SCALE = 300.0
MIN_GROSS_CONTRACTS = 5000  # below this the intraday tape is noise
MIN_VOL_OI = 1.0            # volume exceeding OI => opening, not closing
MIN_OPENING_ALERTS = 5      # too few alerts to average is not a signal

# Confidence adjustment is capped deliberately. A layer with no demonstrated
# edge should not be able to swing a decision far, even once live.
MAX_CONF_ADJ = 10.0


def _f(v, d=None):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _clamp(x, lo=-100.0, hi=100.0):
    return max(lo, min(hi, x))


@dataclass
class Confirmation:
    symbol: str
    direction: str
    available: bool = False
    score: float = 0.0                    # -100 (contradicts) .. +100 (confirms)
    verdict: str = "UNAVAILABLE"          # CONFIRM / NEUTRAL / CONTRADICT
    base_confidence: float = 0.0
    adjusted_confidence: float = 0.0
    expected_move_mult: float = 1.0       # gamma-derived, for stops/sizing
    expected_move_pct: Optional[float] = None
    components: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    shadow: bool = True
    at: str = ""

    def summary(self) -> str:
        if not self.available:
            return f"{self.symbol}: options data unavailable — no change"
        return (f"{self.symbol} {self.verdict} score={self.score:+.0f} "
                f"conf {self.base_confidence:.0f}->{self.adjusted_confidence:.0f} "
                f"exp_move x{self.expected_move_mult:.2f}"
                + ("  [SHADOW]" if self.shadow else ""))


class OptionsConfirmation:
    """
    Options-derived confirmation for an already-formed technical decision.

    Usage from the production bot, after the confidence threshold filter:

        oc = OptionsConfirmation()
        for trade in high_confidence:
            c = oc.confirm(trade["symbol"], "BUY", trade.get("confidence", 70))
            oc.log_ab(c, trade)
            if not c.shadow and c.verdict == "CONTRADICT":
                continue                      # only once proven
    """

    def __init__(self, api_key: Optional[str] = None, shadow: bool = SHADOW_DEFAULT,
                 cache_ttl: int = 120, timeout: int = 6):
        import requests
        self.api_key = api_key or os.getenv("UW_API_KEY")
        self.shadow = shadow
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, object] = {}
        self._at: Dict[str, float] = {}
        self._lock = threading.Lock()
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}",
                                         "Accept": "application/json"})
        if not self.api_key:
            log.warning("UW_API_KEY not set — options confirmation disabled (fail-open)")

    # ------------------------------------------------------------------ http

    def _get(self, path: str, params: Optional[Dict] = None):
        """Cached GET. Returns None on any failure — never raises."""
        if not self.api_key:
            return None
        key = f"{path}:{sorted((params or {}).items())}"
        with self._lock:
            if key in self._cache and time.time() - self._at.get(key, 0) < self.cache_ttl:
                return self._cache[key]
        try:
            r = self.session.get(BASE + path, params=params or {}, timeout=self.timeout)
            if r.status_code != 200:
                return None
            d = r.json().get("data")
        except Exception as e:
            log.debug(f"UW {path} failed: {e}")
            return None
        with self._lock:
            self._cache[key] = d
            self._at[key] = time.time()
        return d

    # ------------------------------------------------------- components

    def _raw_tape_ratio(self, sym: str) -> Optional[float]:
        """Delta-weighted aggressor imbalance, normalised by gross volume."""
        rows = self._get(f"/stock/{sym}/net-prem-ticks")
        if not isinstance(rows, list) or not rows:
            return None
        nd = cv = pv = 0.0
        for r in rows:
            nd += _f(r.get("net_delta"), 0.0) or 0.0
            cv += _f(r.get("call_volume"), 0.0) or 0.0
            pv += _f(r.get("put_volume"), 0.0) or 0.0
        gross = cv + pv
        # Early in the session there are few ticks and net_delta is noise.
        # Below this the reading is not trustworthy at all.
        if gross < MIN_GROSS_CONTRACTS:
            return None
        return nd / (gross * 100.0)

    def _tape_bias(self, sym: str) -> Optional[float]:
        """
        Today's aggressor imbalance, MEASURED RELATIVE TO THE MARKET.

        Aggressor side matters more than raw volume: NVDA on 2026-09-08 traded
        18,811 calls, of which 8,323 lifted the ask and 8,961 hit the bid — net
        call volume NEGATIVE despite heavy call activity. A filter keying on
        volume alone reads that as bullish and is simply wrong.

        THE MARKET SUBTRACTION IS NOT OPTIONAL. Sampled across 25 large names,
        the cross-sectional median of this ratio was -0.0120 with sd 0.0142 —
        i.e. against a zero baseline almost every stock scores bearish on any
        given day, because the whole tape carries a market-wide component.
        Scoring the absolute level would mostly measure beta, which is exactly
        the error that made large option blocks look predictive (+2.74%, t+2.9)
        until returns were taken relative to SPY, whereupon the effect vanished.

        So the score is this stock's imbalance minus SPY's on the same day.
        Scale is set from the observed cross-sectional spread: ~2 sd maps to
        roughly +-85, so the output actually uses its range instead of sitting
        at NEUTRAL forever.
        """
        r = self._raw_tape_ratio(sym)
        if r is None:
            return None
        mkt = 0.0 if sym == MARKET_REF else (self._raw_tape_ratio(MARKET_REF) or 0.0)
        return _clamp((r - mkt) * TAPE_SCALE)

    def _opening_bias(self, sym: str) -> Optional[float]:
        """
        Premium-weighted ask-vs-bid on OPENING single-leg alerts only.

        Restricted deliberately:
          multi-leg      spreads are not directional conviction (PCG showed
                         247,197 volume of which 245,031 was spread legs)
          vol > OI       more contracts traded today than existed beforehand,
                         so the flow is opening new positions rather than
                         closing old ones. Closing flow says a position is
                         LEAVING, which is the opposite inference.

        NOT filtered on `all_opening_trades`: that flag was false on 200 of 200
        NVDA alerts, so requiring it silently discarded every row and this
        component returned "unavailable" for every symbol while appearing to
        work. volume_oi_ratio >= 1 is true for ~30% of alerts and expresses the
        same idea with data that actually exists.

        Bullish = bought calls or sold puts; bearish = the inverse. Direction
        never comes from call/put alone.
        """
        rows = self._get(f"/stock/{sym}/flow-alerts", {"limit": 200})
        if not isinstance(rows, list) or not rows:
            return None
        bull = bear = 0.0
        used = 0
        for r in rows:
            if r.get("has_multileg") or not r.get("has_singleleg"):
                continue
            if (_f(r.get("volume_oi_ratio"), 0.0) or 0.0) < MIN_VOL_OI:
                continue
            ask = _f(r.get("total_ask_side_prem"), 0.0) or 0.0
            bid = _f(r.get("total_bid_side_prem"), 0.0) or 0.0
            if ask + bid <= 0:
                continue
            is_call = str(r.get("type", "")).lower() == "call"
            # bought call / sold put -> bullish
            bull += ask if is_call else bid
            bear += bid if is_call else ask
            used += 1
        tot = bull + bear
        if tot <= 0 or used < MIN_OPENING_ALERTS:
            return None
        # Observed cross-sectional sd of this ratio is ~0.137, so it already
        # spans a usable range; scale ~2 sd to +-82.
        return _clamp((bull - bear) / tot * OPENING_SCALE)

    def _iv_context(self, sym: str) -> Optional[float]:
        """
        IV rank as mild crowding context, not a directional signal.

        Very high IV rank means the option market already expects a large move,
        so a long entry is paying up for it. Small, negative-leaning weight.
        """
        d = self._get(f"/stock/{sym}/volatility/stats")
        if not isinstance(d, dict):
            return None
        rank = _f(d.get("iv_rank"))
        if rank is None:
            return None
        # rank 0 -> +40 (vol cheap), 50 -> 0, 100 -> -40 (vol rich)
        return _clamp((50.0 - rank) * 0.8)

    def _gamma_regime(self, sym: str) -> Optional[float]:
        """
        Expected-move multiplier from dealer gamma. MAGNITUDE ONLY.

        Measured on SPY/QQQ: normalised next-day move ran ~1.07x trailing vol
        at the most negative net gamma down to ~0.65x at the most positive, and
        the effect survived a trailing-volatility control (t+2.9), so it is not
        merely a proxy for the current vol regime.

        Returns a multiplier to apply to ATR-derived stop distance and to
        position sizing. Deliberately excluded from the directional score.
        """
        rows = self._get(f"/stock/{sym}/greek-exposure")
        if not isinstance(rows, list) or len(rows) < 60:
            return None
        nets = []
        for g in rows:
            cg, pg = _f(g.get("call_gamma")), _f(g.get("put_gamma"))
            if cg is None or pg is None:
                continue
            nets.append(cg + pg)
        if len(nets) < 60:
            return None
        cur = nets[-1]
        pct = sum(1 for x in nets if x <= cur) / len(nets)   # 0..1
        # percentile 0 (most negative gamma) -> 1.07x ; 1.0 (most positive) -> 0.65x
        return 1.07 - 0.42 * pct

    # ---------------------------------------------------------------- public

    def confirm(self, symbol: str, direction: str = "BUY",
                base_confidence: float = 70.0) -> Confirmation:
        """Never raises. Returns available=False if anything is missing."""
        sym = (symbol or "").upper().strip()
        c = Confirmation(symbol=sym, direction=(direction or "BUY").upper(),
                         base_confidence=float(base_confidence or 0.0),
                         adjusted_confidence=float(base_confidence or 0.0),
                         shadow=self.shadow,
                         at=datetime.now(timezone.utc).isoformat())
        if not sym or not self.api_key:
            c.notes.append("no symbol or no API key")
            return c

        try:
            tape = self._tape_bias(sym)
            opening = self._opening_bias(sym)
            iv = self._iv_context(sym)
            gam = self._gamma_regime(sym)
        except Exception as e:                      # defensive: must not break the bot
            log.debug(f"confirmation failed for {sym}: {e}")
            c.notes.append(f"error: {e}")
            return c

        parts, weights = [], []
        for name, val, w in (("tape", tape, W_TAPE),
                             ("opening", opening, W_OPENING),
                             ("iv", iv, W_IV)):
            if val is None:
                c.notes.append(f"{name} unavailable")
                continue
            c.components[name] = round(val, 1)
            parts.append(val * w)
            weights.append(w)

        if not parts:
            c.notes.append("no directional components available")
            return c

        # Re-normalise so a missing component does not silently damp the score.
        raw = sum(parts) / sum(weights)

        # Damp when the components disagree with each other. AMD on 2026-09-09
        # read tape +100 against opening -54 and still netted to CONFIRM; a
        # verdict whose own inputs point opposite ways is weaker evidence than
        # the arithmetic mean suggests, and should not be presented as equal.
        signs = [1 if v > 5 else -1 if v < -5 else 0
                 for k, v in c.components.items() if k != "gamma_pctile_mult"]
        voting = [s for s in signs if s != 0]
        if len(voting) > 1:
            agreement = abs(sum(voting)) / len(voting)      # 1.0 = unanimous
            raw *= (0.5 + 0.5 * agreement)
            c.components["agreement"] = round(agreement, 2)
        # A SELL/short decision inverts the reading.
        c.score = _clamp(raw if c.direction in ("BUY", "LONG") else -raw)
        c.available = True

        if gam is not None:
            c.expected_move_mult = round(gam, 3)
            c.components["gamma_pctile_mult"] = round(gam, 3)
        else:
            c.notes.append("gamma unavailable")

        c.verdict = ("CONFIRM" if c.score >= CONFIRM_AT else
                     "CONTRADICT" if c.score <= CONTRADICT_AT else "NEUTRAL")
        adj = _clamp(c.score / 100.0 * MAX_CONF_ADJ, -MAX_CONF_ADJ, MAX_CONF_ADJ)
        c.adjusted_confidence = round(_clamp(c.base_confidence + adj, 0.0, 100.0), 1)
        return c

    # ------------------------------------------------------------------ A/B

    def log_ab(self, c: Confirmation, trade: Optional[Dict] = None,
               path: str = AB_LOG) -> None:
        """
        Append one paired observation.

        This is the whole point of shipping in shadow: the production bot keeps
        acting on its own confidence, while every decision is recorded with the
        options opinion attached. Joining these rows to realised P&L later
        answers whether CONFIRM trades beat CONTRADICT trades. Until that join
        shows a difference, the layer stays in shadow.
        """
        try:
            row = asdict(c)
            if trade:
                row["trade"] = {k: trade.get(k) for k in
                                ("symbol", "confidence", "action", "reason",
                                 "capital_deployed", "quantity", "entry_price")
                                if k in trade}
            with open(path, "a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except Exception as e:
            log.debug(f"A/B log write failed: {e}")

    def annotate(self, trades: List[Dict], direction: str = "BUY") -> List[Dict]:
        """
        Attach a confirmation to each trade and log the pair.

        In shadow mode the returned list is UNCHANGED in content and order —
        only extra keys are added. That is the safety property: dropping this
        call into the production path cannot alter what it trades.
        """
        out = []
        for t in trades or []:
            try:
                c = self.confirm(t.get("symbol", ""), direction,
                                 t.get("confidence", 70))
                self.log_ab(c, t)
                t = dict(t)
                t["uw_confirmation"] = {
                    "score": c.score, "verdict": c.verdict,
                    "adjusted_confidence": c.adjusted_confidence,
                    "expected_move_mult": c.expected_move_mult,
                    "available": c.available,
                }
                if c.available:
                    log.info("  📊 %s", c.summary())
            except Exception as e:
                log.debug(f"annotate failed for {t.get('symbol')}: {e}")
            out.append(t)
        return out


def analyse_ab(path: str = AB_LOG) -> str:
    """
    Read the A/B log and report whether the layer earned its place.

    Deliberately blunt about sample size. The block backtest produced three
    convincing false positives at n in the thousands; a few dozen paired trades
    prove nothing, and this says so rather than printing an encouraging number.
    """
    try:
        rows = [json.loads(l) for l in open(path) if l.strip()]
    except FileNotFoundError:
        return "no A/B log yet"
    except Exception as e:
        return f"could not read A/B log: {e}"

    rows = [r for r in rows if r.get("available")]
    if not rows:
        return "A/B log has no rows with options data available"

    by = {}
    for r in rows:
        by.setdefault(r.get("verdict", "?"), []).append(r)
    out = [f"A/B log: {len(rows)} decisions with options data"]
    for v in ("CONFIRM", "NEUTRAL", "CONTRADICT"):
        g = by.get(v, [])
        pnl = [x["trade"]["pnl"] for x in g
               if isinstance(x.get("trade"), dict) and x["trade"].get("pnl") is not None]
        if pnl:
            wins = sum(1 for p in pnl if p > 0)
            out.append(f"  {v:<11} n={len(g):<4} with P&L={len(pnl):<4} "
                       f"mean={sum(pnl)/len(pnl):+.2f} win={wins/len(pnl)*100:.0f}%")
        else:
            out.append(f"  {v:<11} n={len(g):<4} (no realised P&L joined yet)")
    out.append("  NOTE: needs >=100 closed trades per bucket before it means anything.")
    return "\n".join(out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import sys
    syms = sys.argv[1:] or ["NVDA", "AAPL", "TSLA", "SPY"]
    oc = OptionsConfirmation()
    print(f"shadow={oc.shadow}\n")
    for s in syms:
        c = oc.confirm(s, "BUY", 72)
        print(c.summary())
        print(f"    components: {c.components}")
        if c.notes:
            print(f"    notes: {c.notes}")
    print()
    print(analyse_ab())
