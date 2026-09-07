"""
Phase 1: Unusual Whales Alert Filter

Reduces false positives by filtering alerts based on:
1. Notional value threshold
2. Options volume vs open interest ratio
3. Institutional vs retail flow signals
4. Contract liquidity (bid-ask spread)

Target: 83% false positive elimination (reduce 100 alerts to ~17 real signals)
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class Phase1AlertFilter:
    """Phase 1: Filter Unusual Whales alerts"""

    def __init__(
        self,
        min_notional_usd_m: float = 1.0,  # $1M minimum
        min_volume_oi_ratio: float = 0.15,  # Volume/OI > 15%
        max_spread_pct: float = 0.05,  # Bid-ask spread < 5%
    ):
        self.min_notional_usd_m = min_notional_usd_m
        self.min_volume_oi_ratio = min_volume_oi_ratio
        self.max_spread_pct = max_spread_pct
        self.stats = {
            "alerts_received": 0,
            "alerts_passed": 0,
            "rejected_size": 0,
            "rejected_liquidity": 0,
            "rejected_spread": 0,
        }

    def filter_alert(self, alert: Dict) -> Optional[Dict]:
        """
        Filter a single Unusual Whales alert.

        Args:
            alert: UW API alert dict

        Returns: Alert dict if passes, None if rejected
        """
        self.stats["alerts_received"] += 1

        # Filter 1: Notional value threshold
        notional_usd_m = alert.get("notional_value_usd_millions", 0)
        if notional_usd_m < self.min_notional_usd_m:
            self.stats["rejected_size"] += 1
            logger.debug(f"❌ Alert rejected: Size ${notional_usd_m:.1f}M < ${self.min_notional_usd_m:.1f}M")
            return None

        # Filter 2: Volume/OI ratio (institutional activity indicator)
        volume = alert.get("volume", 0)
        open_interest = alert.get("open_interest", 1)  # Avoid divide by zero
        volume_oi_ratio = volume / open_interest if open_interest > 0 else 0

        if volume_oi_ratio < self.min_volume_oi_ratio:
            self.stats["rejected_liquidity"] += 1
            logger.debug(f"❌ Alert rejected: Vol/OI {volume_oi_ratio:.2%} < {self.min_volume_oi_ratio:.2%}")
            return None

        # Filter 3: Bid-ask spread (liquidity quality)
        bid = alert.get("bid", 0)
        ask = alert.get("ask", 0)
        if ask > 0:
            spread_pct = (ask - bid) / ask
            if spread_pct > self.max_spread_pct:
                self.stats["rejected_spread"] += 1
                logger.debug(f"❌ Alert rejected: Spread {spread_pct:.2%} > {self.max_spread_pct:.2%}")
                return None

        # PASSED all filters
        self.stats["alerts_passed"] += 1
        logger.info(
            f"✅ Alert passed Phase 1: {alert.get('symbol')} ${notional_usd_m:.1f}M "
            f"(Vol/OI={volume_oi_ratio:.2%}, Spread={spread_pct:.2%})"
        )

        return alert

    def filter_alerts(self, alerts: List[Dict]) -> List[Dict]:
        """Filter batch of alerts"""
        return [a for a in [self.filter_alert(alert) for alert in alerts] if a is not None]

    def get_pass_rate(self) -> float:
        """Calculate pass rate (%)"""
        if self.stats["alerts_received"] == 0:
            return 0
        return self.stats["alerts_passed"] / self.stats["alerts_received"] * 100

    def log_stats(self):
        """Log filter statistics"""
        pass_rate = self.get_pass_rate()
        logger.info("\n" + "=" * 80)
        logger.info("PHASE 1: ALERT FILTER STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Alerts received: {self.stats['alerts_received']}")
        logger.info(f"Alerts passed: {self.stats['alerts_passed']} ({pass_rate:.1f}%)")
        logger.info(f"Rejected (size): {self.stats['rejected_size']}")
        logger.info(f"Rejected (liquidity): {self.stats['rejected_liquidity']}")
        logger.info(f"Rejected (spread): {self.stats['rejected_spread']}")
        logger.info("=" * 80 + "\n")
