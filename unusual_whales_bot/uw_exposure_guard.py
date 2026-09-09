"""
Exposure Conflict Guard

FOUND Sep 8 in the live paper book: the bot held **TQQQ and SQQQ at the same
time** — 3x long Nasdaq alongside 3x short Nasdaq. The P&L showed them
cancelling almost exactly (TQQQ -0.25%, SQQQ +0.21%).

That is strictly worse than holding nothing: net directional exposure is ~zero,
both leveraged ETFs bleed to volatility decay, and the spread was paid twice.

Why nothing caught it:
  - `PositionConsolidation` resolves CALL vs PUT conflicts on the SAME ticker.
  - `has_open_position()` blocks re-entering the SAME ticker.
  - Neither has any concept of DIFFERENT tickers with opposing exposure.

This module adds two checks, applied before entry:

  1. INVERSE CONFLICT (hard block)
     Two instruments tracking the same underlying family with opposite
     direction. Long-only means holding both is self-cancelling by
     construction.

  2. FAMILY / SECTOR CONCENTRATION (soft cap)
     Several positions in the same ETF family or the same sector is one bet
     wearing several names. UW alerts carry `sector` and `industry_type`, so
     this costs nothing extra to evaluate.
"""

import logging
from typing import Dict, List, Optional, Tuple
from collections import Counter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ETF family map: ticker -> (family, direction, leverage)
#   direction +1 = long exposure to the family, -1 = inverse exposure
# Long-only book: holding a +1 and a -1 in the same family is self-cancelling.
# ---------------------------------------------------------------------------
ETF_FAMILIES: Dict[str, Tuple[str, int, float]] = {
    # Nasdaq-100
    "QQQ": ("NDX", +1, 1), "QLD": ("NDX", +1, 2), "TQQQ": ("NDX", +1, 3),
    "PSQ": ("NDX", -1, 1), "QID": ("NDX", -1, 2), "SQQQ": ("NDX", -1, 3),
    # S&P 500
    "SPY": ("SPX", +1, 1), "VOO": ("SPX", +1, 1), "IVV": ("SPX", +1, 1),
    "SSO": ("SPX", +1, 2), "UPRO": ("SPX", +1, 3), "SPXL": ("SPX", +1, 3),
    "SH": ("SPX", -1, 1), "SDS": ("SPX", -1, 2),
    "SPXU": ("SPX", -1, 3), "SPXS": ("SPX", -1, 3),
    # Dow
    "DIA": ("DJI", +1, 1), "UDOW": ("DJI", +1, 3), "SDOW": ("DJI", -1, 3),
    # Russell 2000
    "IWM": ("RUT", +1, 1), "TNA": ("RUT", +1, 3), "TZA": ("RUT", -1, 3),
    # Semiconductors
    "SMH": ("SEMI", +1, 1), "SOXX": ("SEMI", +1, 1),
    "SOXL": ("SEMI", +1, 3), "SOXS": ("SEMI", -1, 3),
    # Financials
    "XLF": ("FIN", +1, 1), "FAS": ("FIN", +1, 3), "FAZ": ("FIN", -1, 3),
    # Energy
    "XLE": ("ENERGY", +1, 1), "ERX": ("ENERGY", +1, 2), "ERY": ("ENERGY", -1, 2),
    "USO": ("OIL", +1, 1), "UCO": ("OIL", +1, 2), "SCO": ("OIL", -1, 2),
    "BNO": ("OIL", +1, 1),
    # Gold / miners
    "GLD": ("GOLD", +1, 1), "IAU": ("GOLD", +1, 1),
    "NUGT": ("GOLDMINERS", +1, 2), "DUST": ("GOLDMINERS", -1, 2),
    "JNUG": ("JRGOLDMINERS", +1, 2), "JDST": ("JRGOLDMINERS", -1, 2),
    # Biotech
    "XBI": ("BIOTECH", +1, 1), "LABU": ("BIOTECH", +1, 3), "LABD": ("BIOTECH", -1, 3),
    # China
    "FXI": ("CHINA", +1, 1), "YINN": ("CHINA", +1, 3), "YANG": ("CHINA", -1, 3),
    # Treasuries
    "TLT": ("LONGBOND", +1, 1), "TMF": ("LONGBOND", +1, 3), "TMV": ("LONGBOND", -1, 3),
    # Natural gas
    "BOIL": ("NATGAS", +1, 2), "KOLD": ("NATGAS", -1, 2),
    # Volatility (inverse of equity direction by nature)
    "UVXY": ("VOL", +1, 1.5), "VXX": ("VOL", +1, 1), "SVXY": ("VOL", -1, 1),
}

# ---------------------------------------------------------------------------
# CORRELATION CLUSTERS — families that are one bet wearing several names.
#
# Found Sep 8 from a live flow screenshot: SOXX, SPY and TQQQ all passed the
# guard because they sit in different FAMILIES (SEMI, SPX, NDX). Nothing
# conflicted, yet all three are long US equity beta — three positions, one bet,
# and in a risk-off event they correlate to 1 precisely when it matters.
#
# Position COUNT also understates the risk: TQQQ is 3x leveraged, so one TQQQ
# position carries three times the index exposure of one SPY position. The cap
# is therefore LEVERAGE-WEIGHTED, not a headcount.
# ---------------------------------------------------------------------------
FAMILY_CLUSTER: Dict[str, str] = {
    "NDX": "US_EQUITY", "SPX": "US_EQUITY", "DJI": "US_EQUITY",
    "RUT": "US_EQUITY", "SEMI": "US_EQUITY", "FIN": "US_EQUITY",
    "BIOTECH": "US_EQUITY",
    "OIL": "ENERGY_CMDTY", "ENERGY": "ENERGY_CMDTY", "NATGAS": "ENERGY_CMDTY",
    "GOLD": "METALS", "GOLDMINERS": "METALS", "JRGOLDMINERS": "METALS",
    "LONGBOND": "RATES",
    "CHINA": "INTL_EQUITY",
    # VOL is deliberately its own cluster: long volatility HEDGES US_EQUITY
    # rather than adding to it.
    "VOL": "VOLATILITY",
}


class ExposureGuard:
    """Blocks self-cancelling and over-concentrated entries."""

    def __init__(
        self,
        block_inverse: bool = True,
        max_per_family: int = 2,
        max_per_sector: int = 4,
        max_cluster_leverage: float = 3.0,
    ):
        self.block_inverse = block_inverse
        self.max_per_family = max_per_family
        self.max_per_sector = max_per_sector
        # Leverage-weighted cap per correlation cluster. 3.0 allows e.g.
        # SPY(1x) + SOXX(1x) but blocks adding TQQQ(3x) on top.
        self.max_cluster_leverage = max_cluster_leverage
        self.stats = {
            "checked": 0,
            "blocked_inverse": 0,
            "blocked_family": 0,
            "blocked_sector": 0,
            "blocked_cluster": 0,
        }

    @staticmethod
    def family_of(symbol: str) -> Optional[Tuple[str, int, float]]:
        return ETF_FAMILIES.get(str(symbol).upper())

    def check(
        self,
        symbol: str,
        held_symbols: List[str],
        candidate_sector: Optional[str] = None,
        held_sectors: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Returns (allowed, reason).

        `held_symbols` are the tickers currently held (long-only book).
        """
        self.stats["checked"] += 1
        sym = str(symbol).upper()
        held = [str(s).upper() for s in held_symbols]

        fam = self.family_of(sym)

        # ---- 1. Inverse conflict -------------------------------------
        if fam and self.block_inverse:
            family, direction, leverage = fam
            for h in held:
                hf = self.family_of(h)
                if not hf:
                    continue
                h_family, h_direction, h_leverage = hf
                if h_family == family and h_direction != direction:
                    self.stats["blocked_inverse"] += 1
                    return False, (
                        f"INVERSE CONFLICT: {sym} ({family} {direction:+d}, "
                        f"{leverage}x) opposes held {h} ({family} {h_direction:+d}, "
                        f"{h_leverage}x) — self-cancelling in a long-only book"
                    )

        # ---- 2. Family concentration ---------------------------------
        if fam:
            family = fam[0]
            same_family = sum(
                1 for h in held
                if (hf := self.family_of(h)) and hf[0] == family
            )
            if same_family >= self.max_per_family:
                self.stats["blocked_family"] += 1
                return False, (
                    f"CONCENTRATION: already hold {same_family} {family} "
                    f"position(s) (max {self.max_per_family})"
                )

        # ---- 3. Correlation cluster (leverage-weighted) ---------------
        if fam:
            cluster = FAMILY_CLUSTER.get(fam[0])
            if cluster:
                held_lev = 0.0
                held_names = []
                for h in held:
                    hf = self.family_of(h)
                    if hf and FAMILY_CLUSTER.get(hf[0]) == cluster:
                        held_lev += hf[2]
                        held_names.append(f"{h}({hf[2]:g}x)")
                incoming = fam[2]
                if held_lev + incoming > self.max_cluster_leverage:
                    self.stats["blocked_cluster"] += 1
                    return False, (
                        f"CORRELATION: {cluster} exposure would reach "
                        f"{held_lev + incoming:g}x (cap {self.max_cluster_leverage:g}x) — "
                        f"already hold {', '.join(held_names)}, adding {sym}({incoming:g}x). "
                        f"These move together."
                    )

        # ---- 4. Sector concentration ---------------------------------
        if candidate_sector and held_sectors:
            n = sum(1 for s in held_sectors if s and s == candidate_sector)
            if n >= self.max_per_sector:
                self.stats["blocked_sector"] += 1
                return False, (
                    f"CONCENTRATION: already hold {n} {candidate_sector} "
                    f"position(s) (max {self.max_per_sector})"
                )

        return True, "ok"

    @staticmethod
    def audit_book(held_symbols: List[str], cap: float = 3.0) -> List[str]:
        """
        Report conflicts that already exist in the book (as opposed to
        screening a new entry). Used at startup so pre-existing conflicts
        surface instead of sitting there quietly.
        """
        problems = []
        held = [str(s).upper() for s in held_symbols]

        # opposing exposure
        for i, a in enumerate(held):
            fa = ExposureGuard.family_of(a)
            if not fa:
                continue
            for b in held[i + 1:]:
                fb = ExposureGuard.family_of(b)
                if fb and fa[0] == fb[0] and fa[1] != fb[1]:
                    problems.append(
                        f"{a} ({fa[0]} {fa[1]:+d}) vs {b} ({fb[0]} {fb[1]:+d}) — "
                        f"opposing exposure to {fa[0]}"
                    )

        # cluster over-exposure — a book restored from disk can already breach
        # the cap even though every individual entry passed at the time
        by_cluster: Dict[str, List[str]] = {}
        lev: Dict[str, float] = {}
        for h in held:
            hf = ExposureGuard.family_of(h)
            if not hf:
                continue
            c = FAMILY_CLUSTER.get(hf[0])
            if not c:
                continue
            by_cluster.setdefault(c, []).append(f"{h}({hf[2]:g}x)")
            lev[c] = lev.get(c, 0.0) + hf[2]
        for c, total in lev.items():
            if total > cap:
                problems.append(
                    f"{c} exposure {total:g}x exceeds {cap:g}x cap — "
                    f"holding {', '.join(by_cluster[c])}; these move together"
                )
        return problems

    def log_stats(self):
        s = self.stats
        logger.info(
            f"🛡️  Exposure guard: {s['checked']} checked | "
            f"{s['blocked_inverse']} inverse | {s['blocked_family']} family | "
            f"{s['blocked_cluster']} cluster | {s['blocked_sector']} sector"
        )
