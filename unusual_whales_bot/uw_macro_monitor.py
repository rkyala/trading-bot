"""
Macro / Market-Regime Monitor

MOTIVATION
The bot trades single names on options flow and per-name technicals, with no
awareness of the market it is trading into. Hold ten longs when a risk-off
event lands and those ten positions correlate to 1 — the diversification is
illusory exactly when it is needed.

TWO SOURCES, DELIBERATELY SEPARATED

  1. NEWS  (UW /news/headlines)
     Tells you WHAT happened. Today's Iran story appeared here as
     "EXPLOSION SOUNDS REPORTED ON IRAN'S KHARG ISLAND" with is_major=true,
     alongside Brent +0.95% and gold -1%.

     Caveat established by inspection: UW's own `sentiment` field returned
     "neutral" for all 40 headlines in the sample INCLUDING that explosion,
     and `tags` was empty throughout. Neither can be relied on. What is usable
     is `is_major` plus the headline text, so classification here is keyword
     based rather than trusting the vendor's sentiment.

  2. PRICE  (SPY / QQQ / VIX)
     Tells you whether the market CARES. This is the more reliable of the two:
     a macro shock reaches price faster and less ambiguously than any headline
     parser can reach a decision.

WHY BOTH, AND WHY THEY ARE NOT THE SAME GATE
Measured on the actual Iran headline today: SPY moved -0.28% from the open and
VIX sat at 15.51, below its own 20-day max. The news was real; the market
shrugged. A system that halted on headlines alone would have stopped trading
for nothing — and would do so most days.

So the two are wired to different consequences:
    NEWS alone            -> ALERT a human. Never changes trading behaviour.
    PRICE confirmation    -> changes behaviour (size down, then halt entries).

That asymmetry is the point: headlines are for awareness, price is for action.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Regimes, ordered by severity
# ---------------------------------------------------------------------------
NORMAL = "NORMAL"        # trade as usual
CAUTION = "CAUTION"      # size down, raise the confidence floor
RISK_OFF = "RISK_OFF"    # no new entries; existing positions keep their stops
CRISIS = "CRISIS"        # no new entries + flatten longs

SEVERITY = {NORMAL: 0, CAUTION: 1, RISK_OFF: 2, CRISIS: 3}


# ---------------------------------------------------------------------------
# Headline classification.
# Word-boundary matched to avoid the classic false positives ("Iran" inside
# "Iranian" is fine; "war" inside "warrant", "forward" or "software" is not).
# ---------------------------------------------------------------------------
MACRO_PATTERNS: Dict[str, List[str]] = {
    "GEOPOLITICAL": [
        r"\bwar\b", r"\bmissile", r"\bstrike[sd]?\b", r"\bexplosion", r"\battack",
        r"\binvasion\b", r"\bsanction", r"\bmilitary\b", r"\bairstrike",
        r"\biran\b", r"\bisrael", r"\brussia", r"\bukraine", r"\btaiwan\b",
        r"\bnorth korea\b", r"\bnuclear\b", r"\bceasefire\b", r"\bhostilit",
    ],
    "CENTRAL_BANK": [
        r"\bfomc\b", r"\bfederal reserve\b", r"\bpowell\b", r"\brate (cut|hike)",
        r"\bbasis points?\b", r"\becb\b", r"\bbank of japan\b", r"\bboj\b",
        r"\bhawkish\b", r"\bdovish\b",
    ],
    "MACRO_DATA": [
        r"\bcpi\b", r"\bppi\b", r"\binflation\b", r"\bnonfarm\b", r"\bpayroll",
        r"\bunemployment\b", r"\bjobless\b", r"\bgdp\b", r"\brecession\b",
    ],
    "ENERGY_SHOCK": [
        r"\bopec\b", r"\bcrude\b", r"\bbrent\b", r"\boil (shock|price|surge|spike)",
        r"\bstrait of hormuz\b", r"\bpipeline\b", r"\brefinery\b",
    ],
    "MARKET_STRUCTURE": [
        r"\bcircuit breaker\b", r"\btrading halt", r"\bselloff\b", r"\bplunge",
        r"\bcrash\b", r"\brout\b", r"\bflash crash\b", r"\bmargin call",
    ],
}

# Categories that historically move equity indices hardest.
CATEGORY_WEIGHT = {
    "GEOPOLITICAL": 1.0,
    "CENTRAL_BANK": 1.0,
    "MARKET_STRUCTURE": 1.0,
    "MACRO_DATA": 0.7,
    "ENERGY_SHOCK": 0.6,
}


@dataclass
class MacroHeadline:
    time: str
    headline: str
    categories: List[str]
    is_major: bool
    weight: float
    tickers: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# INDEX PUT PRESSURE
#
# Institutions hedge equity books with index puts, so a surge in index put
# BUYING is one of the earliest signs of a book going defensive.
#
# The measurement must use ask-side premium, never put volume. Measured on IWM
# 2026-09-08: $54.2M of puts versus $11.6M of calls reads as 4.7:1 put-heavy
# and screams bearish — but 60% of that put premium was SOLD, and the single
# largest line was $9.34M of the 293 put sold (someone collecting premium that
# IWM holds). Net positioning was BULLISH 1.36:1. A volume-based flag would
# have fired exactly backwards.
#
# Two distinct things are tracked, because they mean different things:
#   directional  near-dated, near-the-money puts bought -> expects a fall soon
#   tail hedge   far-OTM, long-dated puts bought -> paying for crash insurance
# Tail hedging can rise in a calm market and is not a timing signal.
# ---------------------------------------------------------------------------
INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]

TAIL_OTM_PCT = 10.0      # >10% out of the money
TAIL_MIN_DTE = 45        # and >45 days out => insurance, not a directional bet


@dataclass
class PutPressure:
    put_buy_premium: float = 0.0
    call_buy_premium: float = 0.0
    tail_hedge_premium: float = 0.0
    directional_put_premium: float = 0.0
    per_ticker: Dict[str, float] = field(default_factory=dict)

    @property
    def buy_side_put_ratio(self) -> float:
        """
        Among AGGRESSIVELY BOUGHT index options, the share that were puts.

        Self-normalising, and immune to the put-selling that corrupts raw
        put/call volume.
        """
        total = self.put_buy_premium + self.call_buy_premium
        return (self.put_buy_premium / total) if total > 0 else 0.0


@dataclass
class RegimeAssessment:
    regime: str
    reasons: List[str]
    spy_from_open_pct: Optional[float]
    spy_drawdown_pct: Optional[float]
    vix: Optional[float]
    vix_vs_20d_max: Optional[float]
    headlines: List[MacroHeadline]
    put_pressure: Optional["PutPressure"]
    size_multiplier: float
    allow_new_entries: bool

    def summary(self) -> str:
        return f"{self.regime} | " + ("; ".join(self.reasons) if self.reasons else "no stress detected")


class MacroMonitor:
    """Assesses market regime from price, and surfaces macro headlines."""

    def __init__(
        self,
        api_client=None,
        # Price thresholds. Calibrated against today: SPY -0.28%, VIX 15.5 must
        # read NORMAL, otherwise the gate fires on ordinary sessions.
        caution_drawdown_pct: float = 0.75,
        riskoff_drawdown_pct: float = 1.50,
        crisis_drawdown_pct: float = 3.00,
        caution_vix: float = 22.0,
        riskoff_vix: float = 28.0,
        crisis_vix: float = 35.0,
        vix_spike_pct: float = 15.0,
        headline_lookback_minutes: int = 60,
    ):
        self.api_client = api_client
        self.caution_dd = caution_drawdown_pct
        self.riskoff_dd = riskoff_drawdown_pct
        self.crisis_dd = crisis_drawdown_pct
        self.caution_vix = caution_vix
        self.riskoff_vix = riskoff_vix
        self.crisis_vix = crisis_vix
        self.vix_spike_pct = vix_spike_pct
        self.lookback = headline_lookback_minutes
        self._alerted: set = set()

    # ------------------------------------------------------------------ news

    @staticmethod
    def classify_headline(text: str) -> List[str]:
        t = (text or "").lower()
        return [
            cat for cat, pats in MACRO_PATTERNS.items()
            if any(re.search(p, t) for p in pats)
        ]

    def fetch_macro_headlines(self, limit: int = 50) -> List[MacroHeadline]:
        """
        Pull recent headlines and keep the macro-relevant ones.

        Note: UW's `sentiment` is deliberately ignored — it returned "neutral"
        for every headline sampled, including an explosion in Iran.
        """
        if not self.api_client:
            return []
        try:
            raw = self.api_client.get_news_headlines(limit=limit)
        except Exception as e:
            logger.debug(f"news fetch failed: {e}")
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.lookback)
        out: List[MacroHeadline] = []
        for n in raw or []:
            text = n.get("headline") or ""
            cats = self.classify_headline(text)
            if not cats:
                continue
            ts = n.get("created_at") or ""
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if when < cutoff:
                    continue
            except Exception:
                when = None

            is_major = bool(n.get("is_major"))
            weight = max(CATEGORY_WEIGHT.get(c, 0.5) for c in cats)
            if is_major:
                weight *= 1.5

            out.append(MacroHeadline(
                time=(ts[11:16] if len(ts) > 16 else ts),
                headline=text[:160],
                categories=cats,
                is_major=is_major,
                weight=round(weight, 2),
                tickers=n.get("tickers") or [],
            ))
        out.sort(key=lambda h: -h.weight)
        return out

    def new_headlines(self, headlines: List[MacroHeadline]) -> List[MacroHeadline]:
        """Only those not already alerted on (dedupe across cycles)."""
        fresh = [h for h in headlines if h.headline not in self._alerted]
        for h in fresh:
            self._alerted.add(h.headline)
        return fresh

    # ------------------------------------------------------ index put buying

    def index_put_pressure(self) -> PutPressure:
        """
        Measure how hard institutions are BUYING index puts.

        Uses ask-side premium only. Put volume is actively misleading here —
        see the IWM note above.
        """
        pp = PutPressure()
        if not self.api_client:
            return pp

        from datetime import date as _date

        for ticker in INDEX_TICKERS:
            try:
                rows = self.api_client.get_flow_alerts_for_ticker(ticker, limit=200)
            except Exception as e:
                logger.debug(f"index flow fetch failed for {ticker}: {e}")
                continue

            spot = 0.0
            ticker_put_buy = 0.0
            for r in rows or []:
                def _f(k, d=0.0):
                    try:
                        return float(r.get(k) or d)
                    except (TypeError, ValueError):
                        return d

                spot = spot or _f("underlying_price")
                ask = _f("total_ask_side_prem")
                is_put = str(r.get("type", "")).lower().startswith("p")

                if is_put:
                    pp.put_buy_premium += ask
                    ticker_put_buy += ask
                    # classify: insurance or directional
                    strike = _f("strike")
                    try:
                        dte = (datetime.strptime(str(r.get("expiry"))[:10], "%Y-%m-%d").date()
                               - _date.today()).days
                    except Exception:
                        dte = None
                    otm_pct = ((spot - strike) / spot * 100) if spot and strike else 0.0
                    if otm_pct >= TAIL_OTM_PCT and dte is not None and dte >= TAIL_MIN_DTE:
                        pp.tail_hedge_premium += ask
                    else:
                        pp.directional_put_premium += ask
                else:
                    pp.call_buy_premium += ask

            if ticker_put_buy:
                pp.per_ticker[ticker] = ticker_put_buy

        return pp

    # ----------------------------------------------------------------- price

    def _price_state(self) -> Dict:
        from uw_market_data import get_market_data
        import pandas as pd

        md = get_market_data()
        state = {"spy_from_open": None, "spy_drawdown": None,
                 "vix": None, "vix_change": None, "vix_20d_max": None}
        try:
            ticks = md.get_intraday_ticks("SPY", "5m")
            if ticks:
                df = pd.DataFrame(ticks)
                o, hi, last = df["open"].iloc[0], df["high"].max(), df["close"].iloc[-1]
                state["spy_from_open"] = (last - o) / o * 100
                state["spy_drawdown"] = (last - hi) / hi * 100
        except Exception as e:
            logger.debug(f"SPY intraday unavailable: {e}")

        try:
            vix = md.get_underlying_price("VIX")
            state["vix"] = vix
            candles = md.get_historical_candles("VIX", "day", 20)
            if candles:
                closes = [c["close"] for c in candles]
                state["vix_20d_max"] = max(closes)
                if len(closes) >= 2 and closes[-2]:
                    state["vix_change"] = (vix - closes[-2]) / closes[-2] * 100
        except Exception as e:
            logger.debug(f"VIX unavailable: {e}")

        return state

    # ------------------------------------------------------------- assessment

    def assess(self) -> RegimeAssessment:
        px = self._price_state()
        headlines = self.fetch_macro_headlines()
        put_pressure = self.index_put_pressure()

        regime = NORMAL
        reasons: List[str] = []

        dd = px["spy_drawdown"]
        vix = px["vix"]
        vchg = px["vix_change"]

        def escalate(to: str, why: str):
            nonlocal regime
            if SEVERITY[to] > SEVERITY[regime]:
                regime = to
            reasons.append(why)

        if dd is not None:
            if dd <= -self.crisis_dd:
                escalate(CRISIS, f"SPY {dd:.2f}% off session high")
            elif dd <= -self.riskoff_dd:
                escalate(RISK_OFF, f"SPY {dd:.2f}% off session high")
            elif dd <= -self.caution_dd:
                escalate(CAUTION, f"SPY {dd:.2f}% off session high")

        if vix is not None:
            if vix >= self.crisis_vix:
                escalate(CRISIS, f"VIX {vix:.1f}")
            elif vix >= self.riskoff_vix:
                escalate(RISK_OFF, f"VIX {vix:.1f}")
            elif vix >= self.caution_vix:
                escalate(CAUTION, f"VIX {vix:.1f}")

        if vchg is not None and vchg >= self.vix_spike_pct:
            escalate(CAUTION, f"VIX +{vchg:.1f}% on the day")

        # Index put BUYING. Same asymmetry as headlines: it can add a notch of
        # caution but must not set the regime alone. Institutions buy index
        # puts in calm markets too (tail hedging), so on its own it is a poor
        # timing signal — and a volume-based version would have fired
        # backwards on IWM today.
        ratio = put_pressure.buy_side_put_ratio
        if put_pressure.put_buy_premium > 0:
            if ratio >= 0.80 and put_pressure.directional_put_premium > 5_000_000:
                escalate(CAUTION,
                         f"index put buying {ratio:.0%} of bought premium "
                         f"(${put_pressure.directional_put_premium/1e6:.1f}M directional)")
            elif ratio >= 0.70:
                reasons.append(f"elevated index put buying ({ratio:.0%}) — noted, not acted on")

        # Headlines RAISE the alarm but never set the regime on their own.
        # A major macro story with price already soft is worth one extra notch;
        # the same story with price flat is worth a notification only.
        heavy = [h for h in headlines if h.weight >= 1.0]
        if heavy and regime != NORMAL:
            escalate(
                RISK_OFF if regime == CAUTION else regime,
                f"{len(heavy)} major macro headline(s) alongside price weakness",
            )

        size_mult = {NORMAL: 1.0, CAUTION: 0.5, RISK_OFF: 0.0, CRISIS: 0.0}[regime]
        allow = regime in (NORMAL, CAUTION)

        return RegimeAssessment(
            regime=regime,
            reasons=reasons,
            spy_from_open_pct=px["spy_from_open"],
            spy_drawdown_pct=dd,
            vix=vix,
            vix_vs_20d_max=(vix - px["vix_20d_max"]) if (vix and px["vix_20d_max"]) else None,
            headlines=headlines,
            put_pressure=put_pressure,
            size_multiplier=size_mult,
            allow_new_entries=allow,
        )
