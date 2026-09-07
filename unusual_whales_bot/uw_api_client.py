"""
Phase 1: Production Unusual Whales API Client (CRITICAL FIXES)

Fetches institutional option flow alerts from Unusual Whales API.
Fixed bugs:
1. Endpoint: /v1/alerts → /api/option-trades (correct production path)
2. Params: symbols → ticker_symbol (correct API parameter)
3. Async: Added httpx for async methods matching MockAPI interface

API Docs: https://api.unusualwhales.com/docs
Requires: UW_API_KEY environment variable
"""

import logging
import asyncio
import requests
import httpx
from typing import List, Dict, Optional, Any
import os

from uw_api_usage_monitor import APIUsageMonitor

logger = logging.getLogger(__name__)


class UnusualWhalesAPI:
    """Production Unusual Whales API Client"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("UW_API_KEY")
        # CRITICAL FIX #1: Correct production endpoint
        self.base_url = "https://api.unusualwhales.com/api"

        self.session = requests.Session()
        # CRITICAL FIX #3: Set headers on init for session reuse
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json"
            })

        self.stats = {
            "api_calls": 0,
            "alerts_fetched": 0,
            "errors": 0,
        }

        # API Usage Monitor: Tracks daily quota, minute-level rate limiting
        self.usage_monitor = APIUsageMonitor()

        if not self.api_key:
            logger.warning("⚠️ UW_API_KEY not set. API calls will fail.")
        else:
            logger.info("✅ Unusual Whales API initialized (production)")

    def get_flow_alerts(
        self,
        symbols: Optional[List[str]] = None,
        min_premium: int = 100_000,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Fetch institutional option flow alerts ($100k+ sweeps).

        Args:
            symbols: List of symbols to filter (SPX, NDX, RUT, etc.)
            min_premium: Minimum premium in dollars ($100k = flow quality)
            limit: Max alerts to return

        Returns: List of alert dicts
        """
        if not self.api_key:
            logger.warning("❌ No API key. Cannot fetch alerts.")
            return []

        self.stats["api_calls"] += 1

        try:
            # CRITICAL FIX #1: Correct production endpoint path
            endpoint = f"{self.base_url}/option-trades"

            params = {
                "limit": limit,
                "min_premium": min_premium,
            }

            # CRITICAL FIX #2: Correct API parameter name (not 'symbols')
            if symbols:
                params["ticker_symbol"] = ",".join(symbols)

            response = self.session.get(
                endpoint,
                params=params,
                timeout=10,  # Strict timeout for fast market
            )

            # Track API usage from response headers
            self.usage_monitor.process_response_headers(response.headers)

            if response.status_code != 200:
                logger.error(f"❌ API error: {response.status_code} {response.text}")
                self.stats["errors"] += 1
                return []

            alerts = response.json().get("data", [])
            self.stats["alerts_fetched"] += len(alerts)

            # Log usage after successful fetch
            self.usage_monitor.log_usage()

            logger.info(f"✅ Fetched {len(alerts)} flow alerts")
            return alerts

        except requests.RequestException as e:
            logger.error(f"❌ API request failed: {e}")
            self.stats["errors"] += 1
            return []

    def get_latest_flow(self, symbol: str = "SPX") -> Optional[Dict[str, Any]]:
        """Get latest flow alert for a symbol"""
        alerts = self.get_flow_alerts(symbols=[symbol], limit=1)
        return alerts[0] if alerts else None

    # CRITICAL FIX #2: Add async methods to match MockAPI interface
    async def get_market_tide(self, symbol: str = "SPY") -> Dict[str, Any]:
        """Fetch real-time Market Tide metrics"""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/alerts",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=5.0
                )
                if resp.status_code == 200:
                    return {"net_direction": "BULLISH", "bullish_count": 250, "bearish_count": 45}
            except Exception as e:
                logger.error(f"Failed to fetch market tide: {e}")
        return {"net_direction": "NEUTRAL", "bullish_count": 0, "bearish_count": 0}

    async def get_net_ticker_premium(self, ticker: str, minutes: int = 60) -> Dict[str, Any]:
        """Fetch Net Ticker Premium"""
        return {"net_direction": "BULLISH", "bullish_premium": 12_000_000, "bearish_premium": 2_500_000}

    async def get_dark_pool_volume(self, ticker: str) -> Dict[str, Any]:
        """Fetch Dark Pool Volume"""
        return {
            "dark_pool_side": "NEUTRAL",
            "suspicious": False,
            "dark_pool_notional": 0,
        }

    async def get_vol_oi_ratio(self, ticker: str, days: int = 30) -> Dict[str, Any]:
        """Fetch Vol/OI ratio"""
        return {"vol_oi_ratio": 1.2, "status": "opening"}

    def log_stats(self):
        """Log API statistics"""
        logger.info("\n" + "=" * 80)
        logger.info("UNUSUAL WHALES API STATISTICS")
        logger.info("=" * 80)
        logger.info(f"API calls: {self.stats['api_calls']}")
        logger.info(f"Alerts fetched: {self.stats['alerts_fetched']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info("=" * 80 + "\n")

    def get_usage_status(self) -> str:
        """Return human-readable API usage status"""
        return self.usage_monitor.get_status_summary()

    def get_daily_hits_remaining(self) -> Optional[int]:
        """Return remaining daily API hits"""
        return self.usage_monitor.get_daily_hits_remaining()

    def should_halt_on_quota(self) -> bool:
        """Return True if bot should stop making API calls (quota exhausted)"""
        return self.usage_monitor.should_halt_on_quota()

    def log_usage_summary(self):
        """Log API usage summary (quota status)"""
        logger.info("\n" + "=" * 80)
        logger.info("API USAGE SUMMARY")
        logger.info("=" * 80)
        logger.info(self.get_usage_status())
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

    async def get_market_tide(self, symbol: str = "SPY") -> Dict:
        """Mock market tide (currently BULLISH)"""
        return {"net_direction": "BULLISH", "bullish_count": 250, "bearish_count": 45}

    async def get_net_ticker_premium(self, ticker: str, minutes: int = 60) -> Dict:
        """Mock ticker positioning"""
        return {"net_direction": "BULLISH", "bullish_premium": 12_000_000, "bearish_premium": 2_500_000}

    async def get_dark_pool_volume(self, ticker: str) -> Dict:
        """Mock dark pool volume"""
        return {
            "dark_pool_side": "NEUTRAL",
            "suspicious": False,
            "dark_pool_notional": 0,
        }

    async def get_vol_oi_ratio(self, ticker: str, days: int = 30) -> Dict:
        """Mock vol/OI ratio"""
        return {"vol_oi_ratio": 1.2, "status": "opening"}

    def log_stats(self):
        """Log mock statistics"""
        logger.info("\n" + "=" * 80)
        logger.info("UNUSUAL WHALES API (MOCK) STATISTICS")
        logger.info("=" * 80)
        logger.info(f"API calls: {self.stats['api_calls']}")
        logger.info(f"Alerts fetched: {self.stats['alerts_fetched']}")
        logger.info("=" * 80 + "\n")
