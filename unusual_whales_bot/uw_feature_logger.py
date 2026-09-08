"""
Feature & Label Logger — training-data capture for future ML work

RATIONALE
This is the only part of an ML pipeline that is expensive to retrofit: you
cannot recover features you did not record. Every cycle that runs without this
is a training row permanently lost. Models can be built later; the data cannot.

The bot is currently 100% rule-based. That rule system is deliberately the
BASELINE any future model must beat, so its decision and confidence are logged
alongside the features — otherwise "did ML help?" is unanswerable.

WHAT IS LOGGED
  features.jsonl  one row per candidate that reached the decision stage,
                  INCLUDING rejects (a classifier needs negatives, and the
                  informative negatives are the near-misses, not the LEAPs
                  discarded upstream).
  labels.jsonl    one row per closed position, joined by candidate_id.

LABELING — triple barrier (López de Prado)
The bot's exits are already barrier-shaped, so labels fall out of the existing
mechanics rather than needing a separate scheme:
    +1  upper barrier   target hit   (+2.5 ATR)
    -1  lower barrier   stop hit     (-1.5 ATR)
     0  vertical barrier EOD/time    (sign of return kept separately)

LEAKAGE
Every feature is a snapshot taken at DECISION TIME. Nothing here may be
back-filled from a later bar; the label is written only when the position
actually closes.
"""

import json
import logging
import os
import uuid
from datetime import datetime, date
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

FEATURES_FILE = "features.jsonl"
LABELS_FILE = "labels.jsonl"


def _f(value, default=None) -> Optional[float]:
    try:
        x = float(value)
        return x if x == x else default  # reject NaN
    except (TypeError, ValueError):
        return default


class FeatureLogger:
    """Append-only capture of decision-time features and realized outcomes."""

    def __init__(self, features_file: str = FEATURES_FILE, labels_file: str = LABELS_FILE):
        self.features_file = features_file
        self.labels_file = labels_file
        self.stats = {"features": 0, "labels": 0, "errors": 0}

    # ------------------------------------------------------------------ util

    @staticmethod
    def make_id(symbol: str) -> str:
        return f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _dte(expiry: str) -> Optional[int]:
        try:
            return (datetime.strptime(str(expiry)[:10], "%Y-%m-%d").date() - date.today()).days
        except Exception:
            return None

    def _append(self, path: str, row: Dict) -> bool:
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            return True
        except Exception as e:
            self.stats["errors"] += 1
            logger.warning(f"feature log write failed: {e}")
            return False

    # -------------------------------------------------------------- features

    def log_candidate(
        self,
        alert: Dict,
        technicals: Optional[Dict] = None,
        gate_detail: Optional[Dict] = None,
        confidence: Optional[float] = None,
        decision: str = "UNKNOWN",
        reject_reason: Optional[str] = None,
        shares: Optional[int] = None,
        notional: Optional[float] = None,
        candidate_id: Optional[str] = None,
    ) -> str:
        """
        Record one candidate at decision time.

        `decision` is one of: EXECUTED, REJECTED_GATES, REJECTED_EXPOSURE,
        REJECTED_DEDUP, REJECTED_CAP, REJECTED_SIDE, REJECTED_DATA.
        """
        symbol = alert.get("underlying_symbol") or alert.get("symbol") or "UNKNOWN"
        cid = candidate_id or self.make_id(symbol)

        bid, ask = _f(alert.get("nbbo_bid")), _f(alert.get("nbbo_ask"))
        mid = (bid + ask) / 2 if bid and ask else None
        spread = (ask - bid) if bid and ask else None
        spot = _f(alert.get("underlying_price"))
        delta = _f(alert.get("delta"))
        volume = _f(alert.get("volume"))
        oi = _f(alert.get("open_interest"))
        strike = _f(alert.get("strike"))
        t = technicals or {}
        g = gate_detail or {}

        row = {
            "candidate_id": cid,
            "logged_at": datetime.now().isoformat(),
            "symbol": symbol,

            # ---- raw option flow -------------------------------------
            "option_type": str(alert.get("option_type", "")).upper(),
            "strike": strike,
            "expiry": alert.get("expiry"),
            "dte": self._dte(alert.get("expiry")),
            "premium": _f(alert.get("premium")),
            "size": _f(alert.get("size")),
            "volume": volume,
            "open_interest": oi,
            "nbbo_bid": bid,
            "nbbo_ask": ask,
            "option_price": _f(alert.get("price")),
            "iv": _f(alert.get("implied_volatility")),
            "delta": delta,
            "gamma": _f(alert.get("gamma")),
            "theta": _f(alert.get("theta")),
            "vega": _f(alert.get("vega")),
            "rho": _f(alert.get("rho")),
            "ask_vol": _f(alert.get("ask_vol")),
            "bid_vol": _f(alert.get("bid_vol")),
            "mid_vol": _f(alert.get("mid_vol")),
            "multi_vol": _f(alert.get("multi_vol")),
            "tags": alert.get("tags"),
            "sector": alert.get("sector"),
            "industry": alert.get("industry_type"),
            "marketcap": _f(alert.get("marketcap")),
            "next_earnings_date": alert.get("next_earnings_date"),
            "executed_at": alert.get("executed_at"),
            "exchange": alert.get("exchange"),
            "option_chain_id": alert.get("option_chain_id"),

            # ---- derived flow features -------------------------------
            # Net Delta Dollars: the notional directional exposure the
            # institution actually put on, which carries more signal than
            # raw contract volume.
            "net_delta_dollars": (
                volume * delta * 100 * spot
                if None not in (volume, delta, spot) else None
            ),
            "vol_oi_ratio": (volume / oi) if volume and oi else None,
            "spread_abs": spread,
            "spread_pct": (spread / mid) if spread and mid else None,
            "option_mid": mid,
            "moneyness": ((spot - strike) / spot) if spot and strike else None,
            "ask_side_ratio": (
                _f(alert.get("ask_vol"), 0) / volume if volume else None
            ),

            # ---- technicals at decision time -------------------------
            "underlying_price": spot,
            "ma20": t.get("ma20"),
            "ma20_dist_atr": t.get("ma20_dist_atr"),
            "rsi14": t.get("rsi14"),
            "vwap": t.get("vwap"),
            "vwap_dist_atr": t.get("vwap_dist_atr"),
            "atr14": t.get("atr"),

            # ---- rule-system decision (the BASELINE to beat) ---------
            "gate_ma_score": (g.get("ma") or {}).get("score"),
            "gate_rsi_score": (g.get("rsi") or {}).get("score"),
            "gate_vwap_score": (g.get("vwap") or {}).get("score"),
            "confidence": confidence,
            "vetoed": bool(g.get("vetoed")) if g else None,
            "decision": decision,
            "reject_reason": reject_reason,
            "shares": shares,
            "notional": notional,
        }

        if self._append(self.features_file, row):
            self.stats["features"] += 1
        return cid

    # ---------------------------------------------------------------- labels

    def log_outcome(
        self,
        candidate_id: str,
        symbol: str,
        entry_price: float,
        exit_price: float,
        exit_reason: str,
        entry_underlying: Optional[float] = None,
        exit_underlying: Optional[float] = None,
        entry_time: Optional[str] = None,
        quantity: int = 0,
        multiplier: int = 1,
    ) -> None:
        """
        Write the realized outcome for a closed position.

        Triple-barrier label derived from which barrier the exit hit.
        """
        ret = ((exit_price - entry_price) / entry_price) if entry_price else 0.0

        reason = (exit_reason or "").upper()
        if "TARGET" in reason:
            label = 1          # upper barrier
        elif "STOP" in reason:
            label = -1         # lower barrier
        else:
            label = 0          # vertical (time) barrier — EOD, tier2, manual

        holding_minutes = None
        if entry_time:
            try:
                delta_t = datetime.now() - datetime.fromisoformat(entry_time)
                holding_minutes = round(delta_t.total_seconds() / 60.0, 2)
            except Exception:
                pass

        row = {
            "candidate_id": candidate_id,
            "symbol": symbol,
            "closed_at": datetime.now().isoformat(),
            "label": label,                 # triple-barrier target
            "return_pct": round(ret * 100, 4),
            "pnl": round((exit_price - entry_price) * quantity * multiplier, 2),
            "win": ret > 0,
            "exit_reason": exit_reason,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_underlying": entry_underlying,
            "exit_underlying": exit_underlying,
            "underlying_return_pct": (
                round((exit_underlying - entry_underlying) / entry_underlying * 100, 4)
                if entry_underlying and exit_underlying else None
            ),
            "holding_minutes": holding_minutes,
        }

        if self._append(self.labels_file, row):
            self.stats["labels"] += 1

    # ----------------------------------------------------------------- misc

    def dataset_status(self) -> Dict[str, Any]:
        """How much training data exists, and is it enough yet."""
        def count(p):
            try:
                with open(p) as fh:
                    return sum(1 for _ in fh)
            except FileNotFoundError:
                return 0

        n_feat, n_lab = count(self.features_file), count(self.labels_file)
        return {
            "features": n_feat,
            "labels": n_lab,
            # ~1k rows is the rough floor for a ~20-feature tabular model
            # before overfitting dominates.
            "ready_to_train": n_lab >= 1000,
            "pct_to_1k": round(min(n_lab / 1000 * 100, 100), 1),
        }

    def log_stats(self):
        s = self.dataset_status()
        logger.info(
            f"🗃️  Training data: {s['features']} feature rows, {s['labels']} labels "
            f"({s['pct_to_1k']}% toward a 1k-row minimum)"
        )
