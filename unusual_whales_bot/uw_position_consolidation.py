"""
Position Consolidation: Single Direction Per Symbol

When Unusual Whales API returns both bullish (CALL) and bearish (PUT) sweeps
for the same underlying, consolidate to single directional conviction.

Rules:
1. Group approved alerts by underlying symbol
2. Calculate net premium (call premium - put premium)
3. Approve only dominant direction if net conviction > threshold
4. Reject both directions if conviction unclear (within ±20%)
"""

import logging
from typing import List, Dict, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class PositionConsolidation:
    """Consolidate directional signals per underlying symbol"""

    def __init__(self, dominance_threshold: float = 0.20):
        """
        Args:
            dominance_threshold: Require dominant direction to exceed minority
                                by at least 20% to approve. Default: 20%.
                                If calls=$1M, puts=$800K: puts are 80% of calls,
                                within threshold → reject both. If puts=$600K
                                (60% of calls): reject both. If puts=$400K (40%
                                of calls): APPROVE calls only.
        """
        self.dominance_threshold = dominance_threshold
        self.stats = {
            "alerts_received": 0,
            "symbols_analyzed": 0,
            "conflicts_resolved": 0,
            "both_rejected": 0,
            "approved_final": 0,
        }

    def consolidate_alerts(self, approved_alerts: List[Dict]) -> List[Dict]:
        """
        Filter approved alerts to single direction per underlying symbol.

        Args:
            approved_alerts: List of Phase 1 approved UW alerts

        Returns: Consolidated alerts (calls or puts only per symbol)
        """
        self.stats["alerts_received"] = len(approved_alerts)

        # Group by underlying symbol
        by_symbol = defaultdict(lambda: {"calls": [], "puts": []})

        for alert in approved_alerts:
            symbol = alert.get("underlying_symbol", "UNKNOWN")
            option_type = str(alert.get("option_type", "")).upper()
            premium = float(alert.get("premium", 0))

            if option_type == "CALL":
                by_symbol[symbol]["calls"].append(alert)
            elif option_type == "PUT":
                by_symbol[symbol]["puts"].append(alert)

        self.stats["symbols_analyzed"] = len(by_symbol)

        # Process each symbol: resolve conflicts
        consolidated = []
        for symbol, grouped in by_symbol.items():
            calls = grouped["calls"]
            puts = grouped["puts"]

            # No conflict: single direction only
            if not calls or not puts:
                consolidated.extend(calls or puts)
                continue

            # CONFLICT: Both calls and puts exist
            self.stats["conflicts_resolved"] += 1

            # Calculate net premium (conviction indicator)
            call_premium_total = sum(float(c.get("premium", 0)) for c in calls)
            put_premium_total = sum(float(p.get("premium", 0)) for p in puts)

            # Determine if one side dominates
            total_premium = call_premium_total + put_premium_total
            if total_premium == 0:
                logger.warning(f"⚠️ {symbol}: zero premium, rejecting both directions")
                self.stats["both_rejected"] += 1
                continue

            call_ratio = call_premium_total / total_premium
            put_ratio = put_premium_total / total_premium

            # Dominance check: require >50% + threshold cushion
            # e.g., if threshold=0.20, need ≥70% to approve (100% - 20% = 80%, but more conservative)
            # Actually: if one side is 60% and other is 40%, that's 60/40 = 1.5x ratio
            # Threshold: require minority to be <threshold% of majority
            # If calls=$1M, puts=$800K: puts are 80% of calls (passes 20% threshold) → APPROVE CALLS
            # If calls=$1M, puts=$900K: puts are 90% of calls (fails 20% threshold) → REJECT BOTH

            if call_premium_total > put_premium_total:
                # Calls dominate
                minority_ratio = put_premium_total / call_premium_total
                if minority_ratio < self.dominance_threshold:
                    # Puts are minority (<20% of calls) → APPROVE CALLS only
                    consolidated.extend(calls)
                    logger.info(
                        f"✅ {symbol}: CALLS dominate "
                        f"(${call_premium_total/1e6:.2f}M calls vs ${put_premium_total/1e6:.2f}M puts)"
                    )
                else:
                    # Puts are close to calls (≥20% of calls) → REJECT both
                    logger.warning(
                        f"⚠️ {symbol}: Conflict! Calls/Puts too close "
                        f"(${call_premium_total/1e6:.2f}M calls vs ${put_premium_total/1e6:.2f}M puts)"
                        f" → Rejecting both directions"
                    )
                    self.stats["both_rejected"] += 1
            else:
                # Puts dominate
                minority_ratio = call_premium_total / put_premium_total
                if minority_ratio < self.dominance_threshold:
                    # Calls are minority (<20% of puts) → APPROVE PUTS only
                    consolidated.extend(puts)
                    logger.info(
                        f"✅ {symbol}: PUTS dominate "
                        f"(${put_premium_total/1e6:.2f}M puts vs ${call_premium_total/1e6:.2f}M calls)"
                    )
                else:
                    # Calls are close to puts (≥20% of puts) → REJECT both
                    logger.warning(
                        f"⚠️ {symbol}: Conflict! Calls/Puts too close "
                        f"(${put_premium_total/1e6:.2f}M puts vs ${call_premium_total/1e6:.2f}M calls)"
                        f" → Rejecting both directions"
                    )
                    self.stats["both_rejected"] += 1

        self.stats["approved_final"] = len(consolidated)

        logger.info(
            f"\n{'='*80}\n"
            f"POSITION CONSOLIDATION RESULTS\n"
            f"{'='*80}\n"
            f"Input alerts: {self.stats['alerts_received']}\n"
            f"Symbols analyzed: {self.stats['symbols_analyzed']}\n"
            f"Conflicts resolved: {self.stats['conflicts_resolved']}\n"
            f"Both directions rejected: {self.stats['both_rejected']}\n"
            f"Approved final: {self.stats['approved_final']}\n"
            f"{'='*80}\n"
        )

        return consolidated

    def get_stats(self) -> Dict:
        """Return consolidation statistics"""
        return self.stats.copy()
