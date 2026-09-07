"""
Phase 1: Unusual Whales API Client

Fetches institutional option flow alerts from Unusual Whales API.

API Docs: https://unusualwhales.com/api
Requires: UW_API_KEY environment variable
"""

import logging
import requests
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)


class UnusualWhalesAPI:
    """Unusual Whales API client"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("UW_API_KEY")
        self.base_url = "https://api.unusualwhales.com/v1"
        self.session = requests.Session()
        self.stats = {
            "api_calls": 0,
            "alerts_fetched": 0,
            "errors": 0,
        }

        if not self.api_key:
            logger.warning("⚠️ UW_API_KEY not set. API calls will fail.")
        else:
            logger.info("✅ Unusual Whales API initialized")

    def get_flow_alerts(
        self,
        symbols: Optional[List[str]] = None,
        alert_type: str = "flow",  # "flow", "earnings", "sector"
        limit: int = 100,
    ) -> List[Dict]:
        """
        Fetch option flow alerts.

        Args:
            symbols: List of symbols to filter (SPX, NDX, RUT, etc.)
            alert_type: Type of alert ("flow" for institutional flow)
            limit: Max alerts to return

        Returns: List of alert dicts
        """
        if not self.api_key:
            logger.warning("❌ No API key. Cannot fetch alerts.")
            return []

        self.stats["api_calls"] += 1

        try:
            endpoint = f"{self.base_url}/alerts"

            params = {
                "type": alert_type,
                "limit": limit,
            }

            if symbols:
                params["symbols"] = ",".join(symbols)

            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = self.session.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(f"❌ API error: {response.status_code} {response.text}")
                self.stats["errors"] += 1
                return []

            alerts = response.json().get("data", [])
            self.stats["alerts_fetched"] += len(alerts)

            logger.info(f"✅ Fetched {len(alerts)} alerts")
            return alerts

        except requests.RequestException as e:
            logger.error(f"❌ API request failed: {e}")
            self.stats["errors"] += 1
            return []

    def get_latest_flow(self, symbol: str = "SPX") -> Optional[Dict]:
        """Get latest flow alert for a symbol"""
        alerts = self.get_flow_alerts(symbols=[symbol], limit=1)
        return alerts[0] if alerts else None

    def log_stats(self):
        """Log API statistics"""
        logger.info("\n" + "=" * 80)
        logger.info("UNUSUAL WHALES API STATISTICS")
        logger.info("=" * 80)
        logger.info(f"API calls: {self.stats['api_calls']}")
        logger.info(f"Alerts fetched: {self.stats['alerts_fetched']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info("=" * 80 + "\n")


# Mock client for testing (returns synthetic alerts)
class UnusualWhalesMockAPI:
    """Mock UW API for testing without real API key"""

    def __init__(self):
        logger.info("🎭 Unusual Whales API: MOCK MODE")
        self.stats = {
            "api_calls": 0,
            "alerts_fetched": 0,
            "errors": 0,
        }

    def get_flow_alerts(
        self,
        symbols: Optional[List[str]] = None,
        alert_type: str = "flow",
        limit: int = 100,
    ) -> List[Dict]:
        """Return mock alerts"""
        self.stats["api_calls"] += 1

        mock_alerts = [
            {
                "symbol": "SPX",
                "direction": "CALL",
                "notional_value_usd_millions": 8.2,
                "volume": 250,
                "open_interest": 1500,
                "bid": 4.40,
                "ask": 4.60,
                "entry_price": 4.50,
                "strike": 4500,
                "expiration": "2026-09-18",
            },
            {
                "symbol": "NDX",
                "direction": "CALL",
                "notional_value_usd_millions": 5.5,
                "volume": 180,
                "open_interest": 900,
                "bid": 8.20,
                "ask": 8.50,
                "entry_price": 8.35,
                "strike": 14000,
                "expiration": "2026-09-18",
            },
            {
                "symbol": "RUT",
                "direction": "PUT",
                "notional_value_usd_millions": 3.1,
                "volume": 95,
                "open_interest": 600,
                "bid": 2.10,
                "ask": 2.35,
                "entry_price": 2.22,
                "strike": 2050,
                "expiration": "2026-09-18",
            },
        ]

        symbols_filter = symbols or ["SPX", "NDX", "RUT"]
        filtered = [a for a in mock_alerts if a["symbol"] in symbols_filter][:limit]

        self.stats["alerts_fetched"] += len(filtered)
        logger.info(f"✅ [MOCK] Fetched {len(filtered)} alerts")

        return filtered

    def get_latest_flow(self, symbol: str = "SPX") -> Optional[Dict]:
        """Get latest mock alert"""
        alerts = self.get_flow_alerts(symbols=[symbol], limit=1)
        return alerts[0] if alerts else None

    def log_stats(self):
        """Log mock statistics"""
        logger.info("\n" + "=" * 80)
        logger.info("UNUSUAL WHALES API (MOCK) STATISTICS")
        logger.info("=" * 80)
        logger.info(f"API calls: {self.stats['api_calls']}")
        logger.info(f"Alerts fetched: {self.stats['alerts_fetched']}")
        logger.info("=" * 80 + "\n")
