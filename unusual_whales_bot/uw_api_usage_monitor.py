"""
API Usage Monitor: Real-Time Tracking of Unusual Whales API Quota

Tracks daily API hits, minute-level rate limiting, and alerts when quota is low.
All usage data comes from response headers (zero overhead).

Headers tracked:
  - x-uw-daily-req-count: Successful hits today
  - x-uw-token-req-limit: Your daily limit
  - x-uw-minute-req-counter: Hits this minute
  - x-uw-req-per-minute-remaining: Remaining hits/minute
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class APIUsageSnapshot:
    """Point-in-time snapshot of API usage"""
    daily_hits: int
    daily_limit: int
    minute_hits: int
    minute_remaining: int
    minute_reset_ms: int
    timestamp: datetime

    @property
    def daily_percent_used(self) -> float:
        """Percentage of daily quota used"""
        return (self.daily_hits / self.daily_limit * 100) if self.daily_limit > 0 else 0.0

    @property
    def daily_percent_remaining(self) -> float:
        """Percentage of daily quota remaining"""
        return 100.0 - self.daily_percent_used

    @property
    def is_quota_warning(self) -> bool:
        """True if usage is >=75% of daily limit"""
        return self.daily_percent_used >= 75.0

    @property
    def is_quota_critical(self) -> bool:
        """True if usage is >=95% of daily limit"""
        return self.daily_percent_used >= 95.0


class APIUsageMonitor:
    """Real-time API usage tracking from response headers"""

    def __init__(self):
        self.latest_snapshot: Optional[APIUsageSnapshot] = None
        self.warning_threshold = 0.75  # Alert at 75% usage
        self.critical_threshold = 0.95  # Critical at 95% usage
        self.has_logged_warning = False
        self.has_logged_critical = False

    def process_response_headers(self, response_headers: Dict[str, Any]) -> Optional[APIUsageSnapshot]:
        """
        Extract usage data from API response headers.

        Args:
            response_headers: HTTP response headers dict

        Returns: APIUsageSnapshot if headers present, None otherwise
        """
        try:
            # Extract usage headers (case-insensitive lookup)
            daily_hits = int(self._get_header(response_headers, "x-uw-daily-req-count", "0"))
            daily_limit = int(self._get_header(response_headers, "x-uw-token-req-limit", "15000"))
            minute_hits = int(self._get_header(response_headers, "x-uw-minute-req-counter", "0"))
            minute_remaining = int(self._get_header(response_headers, "x-uw-req-per-minute-remaining", "120"))
            minute_reset_ms = int(self._get_header(response_headers, "x-uw-req-per-minute-reset", "60000"))

            snapshot = APIUsageSnapshot(
                daily_hits=daily_hits,
                daily_limit=daily_limit,
                minute_hits=minute_hits,
                minute_remaining=minute_remaining,
                minute_reset_ms=minute_reset_ms,
                timestamp=datetime.utcnow(),
            )

            self.latest_snapshot = snapshot
            self._check_quota_alerts(snapshot)

            return snapshot

        except (ValueError, KeyError) as e:
            logger.debug(f"Could not parse usage headers: {e}")
            return None

    def _get_header(self, headers: Dict[str, Any], key: str, default: str) -> str:
        """Case-insensitive header lookup"""
        # First try exact match
        if key in headers:
            return headers[key]

        # Try lowercase
        if key.lower() in headers:
            return headers[key.lower()]

        # Try uppercase
        if key.upper() in headers:
            return headers[key.upper()]

        # Try mixed case variations
        for header_key in headers:
            if header_key.lower() == key.lower():
                return headers[header_key]

        return default

    def _check_quota_alerts(self, snapshot: APIUsageSnapshot):
        """Log alerts if quota thresholds are exceeded"""
        percent_used = snapshot.daily_percent_used

        # Critical alert (95%+)
        if snapshot.is_quota_critical and not self.has_logged_critical:
            logger.error(
                f"🚨 CRITICAL: API quota at {percent_used:.1f}% "
                f"({snapshot.daily_hits}/{snapshot.daily_limit} hits). "
                f"Only {snapshot.daily_limit - snapshot.daily_hits} hits remaining!"
            )
            self.has_logged_critical = True

        # Warning alert (75%+)
        elif snapshot.is_quota_warning and not self.has_logged_warning:
            logger.warning(
                f"⚠️ WARNING: API quota at {percent_used:.1f}% "
                f"({snapshot.daily_hits}/{snapshot.daily_limit} hits). "
                f"{snapshot.daily_limit - snapshot.daily_hits} hits remaining."
            )
            self.has_logged_warning = True

    def log_usage(self) -> bool:
        """
        Log current API usage if snapshot available.

        Returns: True if usage was logged, False if no snapshot
        """
        if not self.latest_snapshot:
            return False

        snapshot = self.latest_snapshot
        status_emoji = "🟢" if snapshot.daily_percent_remaining > 25 else "🟡" if snapshot.daily_percent_remaining > 5 else "🔴"

        logger.info(
            f"{status_emoji} API Usage: {snapshot.daily_hits}/{snapshot.daily_limit} "
            f"({snapshot.daily_percent_used:.1f}% used, "
            f"{snapshot.daily_percent_remaining:.1f}% remaining) | "
            f"Minute: {snapshot.minute_hits} hits, "
            f"{snapshot.minute_remaining} available"
        )

        return True

    def get_daily_hits_remaining(self) -> Optional[int]:
        """Return remaining daily hits, or None if no data"""
        if not self.latest_snapshot:
            return None
        return self.latest_snapshot.daily_limit - self.latest_snapshot.daily_hits

    def should_halt_on_quota(self) -> bool:
        """Return True if bot should stop making API calls (quota exhausted)"""
        if not self.latest_snapshot:
            return False
        return self.latest_snapshot.daily_hits >= self.latest_snapshot.daily_limit

    def get_status_summary(self) -> str:
        """Return human-readable status summary"""
        if not self.latest_snapshot:
            return "⚪ No usage data available yet"

        s = self.latest_snapshot
        status = "🟢 OK"
        if s.is_quota_critical:
            status = "🔴 CRITICAL"
        elif s.is_quota_warning:
            status = "🟡 WARNING"

        return (
            f"{status} | Daily: {s.daily_hits}/{s.daily_limit} "
            f"({s.daily_percent_used:.1f}%) | "
            f"Minute: {s.minute_remaining} remaining"
        )
