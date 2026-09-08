"""
Contract Tradeability Filter (BLOCKER FIX #11 — economic)

Found Sep 8: the bot was executing deep-ITM LEAPs — e.g.
AAPL281215C00100000 (Dec-2028 $100 call with the stock at $316) and
GOOGL271217P00480000 (Dec-2027 $480 put). Round-trip bid-ask on the open book
came to -$4,350 against +$187 of directional P&L: the spread cost roughly 20x
any edge the signal could produce over an intraday hold.

Nothing upstream caught it:
  - Phase 1's spread gate is a PERCENTAGE. AAPL's $4.60 spread on a $226
    contract is 2.0% and passes a 15% gate easily, yet costs $1,380 to round
    trip 3 contracts.
  - Nothing looked at expiry, moneyness, premium, or gamma at all.

This filter screens the CONTRACT (as opposed to the signal), on the principle
that instrument choice, not signal quality, decides whether a short-hold
options strategy can clear its own costs.

Gates:
  1. Days to expiry      — no LEAPs, no same-day lottery tickets
  2. Moneyness (|delta|) — near the money, where gamma actually lives
  3. Absolute spread     — dollar cost, not just percentage
  4. Percentage spread   — relative cost
  5. Premium ceiling     — caps capital and round-trip cost per contract
  6. Minimum gamma       — the position must respond to underlying movement
  7. Cost-to-move ratio  — round-trip spread must be small relative to the
                           contract's expected move on a 1-ATR underlying move
"""

import logging
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ContractFilter:
    """Screens option contracts for short-hold tradeability."""

    def __init__(
        self,
        min_dte: int = 7,
        max_dte: int = 60,
        min_abs_delta: float = 0.25,
        max_abs_delta: float = 0.75,
        max_spread_abs: float = 0.25,
        max_spread_pct: float = 0.06,
        max_premium: float = 30.0,
        min_gamma: float = 0.0005,
        max_cost_to_move: float = 0.50,
    ):
        self.min_dte = min_dte
        self.max_dte = max_dte
        self.min_abs_delta = min_abs_delta
        self.max_abs_delta = max_abs_delta
        self.max_spread_abs = max_spread_abs
        self.max_spread_pct = max_spread_pct
        self.max_premium = max_premium
        self.min_gamma = min_gamma
        self.max_cost_to_move = max_cost_to_move

        self.stats = {
            "received": 0,
            "passed": 0,
            "rejected_dte": 0,
            "rejected_moneyness": 0,
            "rejected_spread_abs": 0,
            "rejected_spread_pct": 0,
            "rejected_premium": 0,
            "rejected_gamma": 0,
            "rejected_cost_to_move": 0,
            "rejected_data": 0,
        }

    # ------------------------------------------------------------------ util

    @staticmethod
    def _f(value, default=None) -> Optional[float]:
        try:
            f = float(value)
            return f if f == f else default  # reject NaN
        except (TypeError, ValueError):
            return default

    @staticmethod
    def days_to_expiry(expiry: str) -> Optional[int]:
        """UW returns expiry as 'YYYY-MM-DD'."""
        if not expiry:
            return None
        try:
            exp = datetime.strptime(str(expiry)[:10], "%Y-%m-%d").date()
            return (exp - date.today()).days
        except Exception:
            return None

    # ---------------------------------------------------------------- filter

    def evaluate(self, alert: Dict, atr: Optional[float] = None) -> Tuple[bool, str]:
        """
        Returns (tradeable, reason). `reason` names the failing gate.
        """
        self.stats["received"] += 1

        bid = self._f(alert.get("nbbo_bid"))
        ask = self._f(alert.get("nbbo_ask"))
        delta = self._f(alert.get("delta"))
        gamma = self._f(alert.get("gamma"), 0.0)
        strike = self._f(alert.get("strike"))
        spot = self._f(alert.get("underlying_price"))
        symbol = alert.get("underlying_symbol", "?")

        if bid is None or ask is None or ask <= 0 or bid <= 0 or delta is None:
            self.stats["rejected_data"] += 1
            return False, "incomplete quote/greeks"

        # --- 1. Days to expiry ------------------------------------------
        dte = self.days_to_expiry(alert.get("expiry"))
        if dte is None:
            self.stats["rejected_data"] += 1
            return False, "unparseable expiry"
        if dte < self.min_dte:
            self.stats["rejected_dte"] += 1
            return False, f"expires in {dte}d (<{self.min_dte})"
        if dte > self.max_dte:
            self.stats["rejected_dte"] += 1
            return False, f"expires in {dte}d (>{self.max_dte}, LEAP)"

        # --- 2. Moneyness via delta -------------------------------------
        ad = abs(delta)
        if ad > self.max_abs_delta:
            self.stats["rejected_moneyness"] += 1
            return False, f"deep ITM (|delta| {ad:.2f} > {self.max_abs_delta})"
        if ad < self.min_abs_delta:
            self.stats["rejected_moneyness"] += 1
            return False, f"far OTM (|delta| {ad:.2f} < {self.min_abs_delta})"

        # --- 3/4. Spread: absolute AND percentage -----------------------
        mid = (bid + ask) / 2.0
        spread = ask - bid
        if spread > self.max_spread_abs:
            self.stats["rejected_spread_abs"] += 1
            return False, f"spread ${spread:.2f} > ${self.max_spread_abs:.2f}"
        spread_pct = spread / mid if mid > 0 else 1.0
        if spread_pct > self.max_spread_pct:
            self.stats["rejected_spread_pct"] += 1
            return False, f"spread {spread_pct:.1%} > {self.max_spread_pct:.0%}"

        # --- 5. Premium ceiling -----------------------------------------
        if mid > self.max_premium:
            self.stats["rejected_premium"] += 1
            return False, f"premium ${mid:.2f} > ${self.max_premium:.0f}"

        # --- 6. Minimum gamma -------------------------------------------
        if gamma is not None and gamma < self.min_gamma:
            self.stats["rejected_gamma"] += 1
            return False, f"gamma {gamma:.5f} < {self.min_gamma}"

        # --- 7. Cost-to-move --------------------------------------------
        # Round-trip spread vs the option's expected move on a 1-ATR move in
        # the underlying. If it costs more to trade than the position can
        # plausibly make, the signal cannot matter.
        if atr and atr > 0:
            expected_move = ad * atr  # first-order option move per 1 ATR
            if expected_move > 0:
                ratio = spread / expected_move
                if ratio > self.max_cost_to_move:
                    self.stats["rejected_cost_to_move"] += 1
                    return False, (
                        f"cost/move {ratio:.2f} > {self.max_cost_to_move} "
                        f"(spread ${spread:.2f} vs ${expected_move:.2f} per ATR)"
                    )

        self.stats["passed"] += 1
        logger.info(
            f"✅ Contract OK: {symbol} {dte}d |delta|={ad:.2f} "
            f"mid=${mid:.2f} spread=${spread:.2f} ({spread_pct:.1%})"
        )
        return True, "ok"

    def filter_alerts(self, alerts: List[Dict], atr_lookup=None) -> List[Dict]:
        """Keep only tradeable contracts. `atr_lookup(symbol) -> float|None`."""
        kept = []
        for a in alerts:
            atr = None
            if atr_lookup:
                try:
                    atr = atr_lookup(a.get("underlying_symbol"))
                except Exception:
                    atr = None
            ok, reason = self.evaluate(a, atr)
            if ok:
                kept.append(a)
            else:
                logger.info(
                    f"⛔ Contract rejected: {a.get('underlying_symbol','?')} "
                    f"{a.get('expiry','?')} {a.get('option_type','?')} — {reason}"
                )
        return kept

    def log_stats(self):
        s = self.stats
        rate = (s["passed"] / s["received"] * 100) if s["received"] else 0
        logger.info("\n" + "=" * 80)
        logger.info("CONTRACT FILTER STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Received: {s['received']} | Passed: {s['passed']} ({rate:.1f}%)")
        logger.info(f"  rejected DTE (LEAP/expiring): {s['rejected_dte']}")
        logger.info(f"  rejected moneyness:           {s['rejected_moneyness']}")
        logger.info(f"  rejected spread (absolute):   {s['rejected_spread_abs']}")
        logger.info(f"  rejected spread (percent):    {s['rejected_spread_pct']}")
        logger.info(f"  rejected premium ceiling:     {s['rejected_premium']}")
        logger.info(f"  rejected low gamma:           {s['rejected_gamma']}")
        logger.info(f"  rejected cost-to-move:        {s['rejected_cost_to_move']}")
        logger.info(f"  rejected bad data:            {s['rejected_data']}")
        logger.info("=" * 80 + "\n")
