"""
Whale Watchlist — track large institutional option positions from open to close

WHY
Following whale positioning means knowing when they LEAVE, not just when they
arrive. A $27.9M block that quietly unwinds two weeks later is a different
story from one held to expiry, and the bot currently has no way to tell them
apart — nothing tracks a contract over time.

THE MECHANISM: OPEN INTEREST
Volume says a trade happened. Open interest says a POSITION exists.

    GOOGL Nov-20 $370C on 2026-09-08
      open interest : 2,288      <- before the block settles
      volume today  : 28,386     <- the $27.9M block plus normal flow

OI settles overnight, so the day after a genuine opening block, OI should jump
by roughly the block size. If it does not, the block was day-traded or offset
and the "whale is positioned" read was wrong. Later, OI falling back toward its
baseline is the position being unwound.

    day 0   OI  2,288   block of 25,000 detected      -> PENDING
    day 1   OI 27,000   +24,712 ~= block size          -> CONFIRMED
    day N   OI 15,000   -44% from peak                 -> UNWINDING
    day M   OI  2,500   back to baseline               -> CLOSED

HONEST LIMITATION
Open interest is aggregate. A fall means *somebody* closed, not necessarily the
same entity that opened. With a contract whose OI is dominated by one block the
inference is strong; on a busy contract it is weak. `oi_concentration` records
how much of the OI the tracked block represents, so the strength of the
inference is visible rather than assumed.
"""

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

WATCHLIST_FILE = "whale_watchlist.json"

PENDING = "PENDING"        # block seen, waiting for OI to settle
CONFIRMED = "CONFIRMED"    # OI rose ~ block size: a real position exists
UNWINDING = "UNWINDING"    # OI falling materially from peak
CLOSED = "CLOSED"          # OI back near baseline
FAILED = "FAILED"          # OI never rose: not an opening position
EXPIRED = "EXPIRED"        # contract past expiry


@dataclass
class WatchedPosition:
    option_chain_id: str
    symbol: str
    option_type: str
    strike: float
    expiry: str

    detected_at: str
    block_size: float
    block_premium: float
    side: str                  # ask_side / bid_side
    bias: str                  # bullish / bearish
    avg_price: float
    underlying_at_detection: float

    baseline_oi: float         # OI at detection, before the block settles
    peak_oi: float = 0.0
    current_oi: float = 0.0
    last_checked: str = ""
    state: str = PENDING
    history: List[Dict] = field(default_factory=list)

    @property
    def oi_gain(self) -> float:
        return self.peak_oi - self.baseline_oi

    @property
    def oi_concentration(self) -> float:
        """
        Share of peak OI attributable to the tracked block.

        High values mean a fall in OI is very likely this position closing.
        Low values mean the contract is busy and the inference is weak.
        """
        return (self.block_size / self.peak_oi) if self.peak_oi > 0 else 0.0

    @property
    def pct_off_peak(self) -> float:
        if self.peak_oi <= 0:
            return 0.0
        return (self.current_oi - self.peak_oi) / self.peak_oi * 100


class WhaleWatchlist:
    """Registers large blocks and follows their open interest until closed."""

    def __init__(
        self,
        api_client=None,
        path: str = WATCHLIST_FILE,
        min_premium: float = 1_000_000,
        min_size_vs_oi: float = 2.0,
        confirm_ratio: float = 0.50,      # OI must rise >= 50% of block size
        unwind_pct: float = -25.0,        # this far off peak = unwinding
        closed_pct: float = -70.0,        # this far off peak = closed
    ):
        self.api = api_client
        self.path = path
        self.min_premium = min_premium
        self.min_size_vs_oi = min_size_vs_oi
        self.confirm_ratio = confirm_ratio
        self.unwind_pct = unwind_pct
        self.closed_pct = closed_pct
        self.positions: Dict[str, WatchedPosition] = {}
        self._load()

    # ----------------------------------------------------------------- state

    def _load(self):
        try:
            with open(self.path) as fh:
                data = json.load(fh)
            self.positions = {k: WatchedPosition(**v) for k, v in data.items()}
            logger.info(f"👁️  Whale watchlist: {len(self.positions)} tracked positions")
        except FileNotFoundError:
            self.positions = {}
        except Exception as e:
            logger.warning(f"watchlist load failed: {e}")
            self.positions = {}

    def _save(self):
        import tempfile
        try:
            data = {k: asdict(v) for k, v in self.positions.items()}
            d = os.path.dirname(os.path.abspath(self.path)) or "."
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except Exception as e:
            logger.warning(f"watchlist save failed: {e}")

    # ------------------------------------------------------------- detection

    @staticmethod
    def _f(v, d=0.0):
        try:
            x = float(v)
            return x if x == x else d
        except (TypeError, ValueError):
            return d

    def qualifies(self, alert: Dict) -> bool:
        """
        Is this a block worth following?

        Deliberately size-vs-OI rather than raw size: 25,000 contracts against
        2,288 OI is a new position; the same size on a contract with 500,000 OI
        is noise.
        """
        prem = self._f(alert.get("premium"))
        size = self._f(alert.get("size"))
        oi = self._f(alert.get("open_interest"))
        if prem < self.min_premium or size <= 0:
            return False
        if oi > 0 and size < oi * self.min_size_vs_oi:
            return False
        return True

    def consider(self, alert: Dict) -> Optional[str]:
        """Register a qualifying block. Returns the chain id if newly added."""
        if not self.qualifies(alert):
            return None
        chain = alert.get("option_chain_id")
        if not chain or chain in self.positions:
            return None

        tags = {str(t).lower() for t in (alert.get("tags") or [])}
        pos = WatchedPosition(
            option_chain_id=chain,
            symbol=alert.get("underlying_symbol") or "?",
            option_type=str(alert.get("option_type", "")).upper(),
            strike=self._f(alert.get("strike")),
            expiry=str(alert.get("expiry") or ""),
            detected_at=datetime.now().isoformat(),
            block_size=self._f(alert.get("size")),
            block_premium=self._f(alert.get("premium")),
            side=("ask_side" if "ask_side" in tags else
                  "bid_side" if "bid_side" in tags else "other"),
            bias=("bullish" if "bullish" in tags else
                  "bearish" if "bearish" in tags else "neutral"),
            avg_price=self._f(alert.get("price")),
            underlying_at_detection=self._f(alert.get("underlying_price")),
            baseline_oi=self._f(alert.get("open_interest")),
        )
        self.positions[chain] = pos
        self._save()
        logger.warning(
            f"👁️  WATCHING: {pos.symbol} {pos.strike:.0f}{pos.option_type[0]} {pos.expiry} — "
            f"{pos.block_size:,.0f} contracts, ${pos.block_premium/1e6:.2f}M, "
            f"{pos.side}/{pos.bias}, baseline OI {pos.baseline_oi:,.0f}"
        )
        return chain

    # --------------------------------------------------------------- polling

    def _fetch_oi(self, pos: WatchedPosition) -> Optional[float]:
        if not self.api:
            return None
        try:
            rows = self.api.get_option_contracts(pos.symbol, expiry=pos.expiry)
            for r in rows or []:
                if r.get("option_symbol") == pos.option_chain_id:
                    return self._f(r.get("open_interest"), None)
        except Exception as e:
            logger.debug(f"OI fetch failed for {pos.option_chain_id}: {e}")
        return None

    def poll(self) -> List[Dict]:
        """
        Refresh OI on every tracked position and return state transitions.

        Intended to run once per day after OI settles, not per cycle — OI only
        updates overnight.
        """
        events = []
        today = date.today()

        for chain, pos in list(self.positions.items()):
            if pos.state in (CLOSED, FAILED, EXPIRED):
                continue

            try:
                exp = datetime.strptime(pos.expiry[:10], "%Y-%m-%d").date()
                if exp < today:
                    pos.state = EXPIRED
                    events.append({"event": EXPIRED, "position": pos})
                    continue
            except Exception:
                pass

            oi = self._fetch_oi(pos)
            if oi is None:
                continue

            prev_state = pos.state
            pos.current_oi = oi
            pos.peak_oi = max(pos.peak_oi, oi)
            pos.last_checked = datetime.now().isoformat()
            pos.history.append({"at": pos.last_checked, "oi": oi})

            gain = oi - pos.baseline_oi

            if pos.state == PENDING:
                if gain >= pos.block_size * self.confirm_ratio:
                    pos.state = CONFIRMED
                else:
                    # FAILED means two SETTLEMENTS with no OI rise — not two
                    # polls. Open interest updates once overnight, so counting
                    # poll entries marked a position FAILED after two calls
                    # minutes apart (observed on HYG). Count distinct dates.
                    days = {str(h.get("at", ""))[:10] for h in pos.history}
                    days.discard("")
                    if len(days) >= 3:  # detection day + two settlements
                        pos.state = FAILED
            elif pos.state in (CONFIRMED, UNWINDING):
                off = pos.pct_off_peak
                if off <= self.closed_pct:
                    pos.state = CLOSED
                elif off <= self.unwind_pct:
                    pos.state = UNWINDING

            if pos.state != prev_state:
                events.append({"event": pos.state, "position": pos})
                logger.warning(
                    f"👁️  {pos.symbol} {pos.strike:.0f}{pos.option_type[0]} "
                    f"{prev_state} -> {pos.state} | OI {pos.baseline_oi:,.0f} -> "
                    f"{oi:,.0f} (peak {pos.peak_oi:,.0f}, {pos.pct_off_peak:+.1f}% off)"
                )

        self._save()
        return events

    # ---------------------------------------------------------------- report

    def active(self) -> List[WatchedPosition]:
        return [p for p in self.positions.values()
                if p.state in (PENDING, CONFIRMED, UNWINDING)]

    def summary(self) -> str:
        if not self.positions:
            return "  (watchlist empty)"
        lines = [f"  {'SYMBOL':<8}{'CONTRACT':<10}{'STATE':<11}{'BLOCK':>9}"
                 f"{'BASE OI':>9}{'PEAK':>9}{'NOW':>9}{'OFF PEAK':>10}{'CONC':>7}"]
        lines.append("  " + "-" * 82)
        for p in sorted(self.positions.values(), key=lambda x: -x.block_premium):
            lines.append(
                f"  {p.symbol:<8}{p.strike:>6.0f}{p.option_type[0]:<4}{p.state:<11}"
                f"{p.block_size:>9,.0f}{p.baseline_oi:>9,.0f}{p.peak_oi:>9,.0f}"
                f"{p.current_oi:>9,.0f}{p.pct_off_peak:>+9.1f}%{p.oi_concentration:>7.0%}"
            )
        return "\n".join(lines)
