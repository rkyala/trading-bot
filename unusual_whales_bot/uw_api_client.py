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
from datetime import datetime

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

    def get_news_headlines(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch recent news headlines (verified endpoint: /api/news/headlines).

        Fields returned: headline, created_at, is_major, sentiment, source,
        tags, tickers, meta.

        NOTE on `sentiment`: verified useless on 2026-09-08 — all 40 sampled
        headlines returned "neutral", including
        "EXPLOSION SOUNDS REPORTED ON IRAN'S KHARG ISLAND". `tags` was empty
        throughout. Callers should classify from the headline text and use
        `is_major` rather than trusting the vendor sentiment field.
        """
        if not self.api_key:
            return []
        try:
            resp = self.session.get(
                f"{self.base_url}/news/headlines",
                params={"limit": limit},
                timeout=8,
            )
            self.usage_monitor.process_response_headers(resp.headers)
            if resp.status_code != 200:
                logger.warning(f"news/headlines returned {resp.status_code}")
                return []
            return resp.json().get("data", [])
        except requests.RequestException as e:
            logger.warning(f"news fetch failed: {e}")
            return []

    # NOTE: get_market_tide is defined ASYNC further down, alongside the other
    # Tier 2 data methods — every caller awaits it. A sync duplicate briefly
    # existed here and was silently shadowed by the later async definition.

    def get_flow_alerts_for_ticker(self, ticker: str, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Aggregated flow alerts for one ticker, carrying total_ask_side_prem /
        total_bid_side_prem — the bought-vs-sold split.

        Aggregated and ~5min lagged, which is fine for a regime read but NOT
        for per-contract questions (it is blind to clean blocks).
        """
        if not self.api_key:
            return []
        try:
            r = self.session.get(f"{self.base_url}/stock/{ticker.upper()}/flow-alerts",
                                 params={"limit": limit}, timeout=12)
            return r.json().get("data", []) if r.status_code == 200 else []
        except requests.RequestException:
            return []

    def get_option_contracts(self, ticker: str, expiry: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Option chain rows for a ticker, carrying open_interest and volume.

        Open interest is the field that distinguishes a real position from
        churn: volume says a trade happened, OI says a position exists. Used by
        the whale watchlist to confirm a block actually opened and to detect it
        being unwound later.
        """
        if not self.api_key:
            return []
        try:
            params = {"expiry": expiry} if expiry else {}
            resp = self.session.get(
                f"{self.base_url}/stock/{ticker.upper()}/option-contracts",
                params=params, timeout=12,
            )
            return resp.json().get("data", []) if resp.status_code == 200 else []
        except requests.RequestException as e:
            logger.debug(f"option-contracts fetch failed for {ticker}: {e}")
            return []

    def get_economic_calendar(self) -> List[Dict[str, Any]]:
        """Scheduled macro events (verified: /api/market/economic-calendar)."""
        if not self.api_key:
            return []
        try:
            resp = self.session.get(f"{self.base_url}/market/economic-calendar", timeout=8)
            return resp.json().get("data", []) if resp.status_code == 200 else []
        except requests.RequestException:
            return []

    # ======================================================================
    # TIER 2 EXIT DATA — real endpoints
    #
    # These were placeholders returning hardcoded values, and two of the four
    # methods Tier2ExitMonitor actually calls (get_net_premium_ticks,
    # get_symbol_flow_recent) did not exist at all. check_all_exits() therefore
    # returned {} every time: the bot logged "Tier 2 exits: ACTIVE" while all
    # four rules were incapable of firing. Verified against the live API on
    # 2026-09-08; every endpoint below returns real data.
    # ======================================================================

    async def _aget(self, path: str, params: Optional[Dict] = None) -> Any:
        """Shared async GET returning the `data` payload, or None."""
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.base_url}{path}",
                    params=params or {},
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Accept": "application/json"},
                    timeout=8.0,
                )
                if resp.status_code == 200:
                    return resp.json().get("data")
                logger.debug(f"{path} -> {resp.status_code}")
        except Exception as e:
            logger.debug(f"{path} failed: {e}")
        return None

    async def get_symbol_flow_recent(self, ticker: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Recent flow alerts for one ticker — feeds Rule #5 (flow exhaustion).

        Normalises `created_at` into a unix `timestamp`, which is what the
        exit monitor compares against its 45-minute cutoff.

        Note this endpoint is an AGGREGATED alert feed lagging ~5 min. That is
        acceptable for a 45-minute exhaustion window, but it is NOT the tape —
        do not use it to answer "did contract X trade".
        """
        rows = await self._aget(f"/stock/{ticker}/flow-alerts", {"limit": limit})
        out = []
        for r in rows or []:
            ts = r.get("created_at") or ""
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                r = {**r, "timestamp": dt.timestamp()}
            except Exception:
                continue
            out.append(r)
        return out

    async def get_net_premium_ticks(self, ticker: str, minutes: int = 30) -> Dict[str, Any]:
        """
        Net call/put premium over the last `minutes` — feeds Rule #1 (put/call
        flip). Backed by /stock/{ticker}/net-prem-ticks, a per-minute series.

        Returns {net_calls, net_puts} as the monitor expects.
        """
        rows = await self._aget(f"/stock/{ticker}/net-prem-ticks")
        if not rows:
            return {}
        recent = rows[-minutes:] if len(rows) > minutes else rows

        def total(key):
            s = 0.0
            for r in recent:
                try:
                    s += float(r.get(key) or 0)
                except (TypeError, ValueError):
                    pass
            return s

        # Premium can be negative (net selling); the ratio downstream needs
        # magnitudes, so clamp at zero.
        return {
            "net_calls": max(total("net_call_premium"), 0.0),
            "net_puts": max(total("net_put_premium"), 0.0),
            "window_minutes": len(recent),
        }

    async def get_dark_pool_volume(self, ticker: str) -> Dict[str, Any]:
        """
        Largest recent dark-pool print — feeds Rule #2 (dark pool reversal).

        Dark pool prints carry no explicit side, so side is inferred from where
        the print landed relative to the NBBO: at/below the bid is
        seller-initiated, at/above the ask is buyer-initiated. Prints inside
        the spread are left unsided rather than guessed.
        """
        rows = await self._aget(f"/darkpool/{ticker}", {"limit": 50})
        if not rows:
            return {}

        best = None
        for r in rows:
            try:
                prem = float(r.get("premium") or 0)
                price = float(r.get("price") or 0)
                bid = float(r.get("nbbo_bid") or 0)
                ask = float(r.get("nbbo_ask") or 0)
            except (TypeError, ValueError):
                continue
            if prem <= 0 or price <= 0:
                continue
            if bid > 0 and price <= bid:
                side = "SELL"
            elif ask > 0 and price >= ask:
                side = "BUY"
            else:
                side = "UNKNOWN"
            if side != "UNKNOWN" and (best is None or prem > best["notional_value"]):
                best = {"side": side, "notional_value": prem,
                        "price": price, "executed_at": r.get("executed_at")}

        return best or {}

    async def get_market_tide(self, symbol: str = "SPY") -> Dict[str, Any]:
        """
        Market-wide options sentiment — feeds Rule #6 (market tide flip).

        Returns `bullish_ratio` (0-1), the share of net premium on the call
        side, which is the field the exit monitor reads.
        """
        rows = await self._aget("/market/market-tide")
        if not rows:
            return {}
        recent = rows[-30:] if len(rows) > 30 else rows

        calls = puts = 0.0
        for r in recent:
            try:
                calls += max(float(r.get("net_call_premium") or 0), 0.0)
                puts += max(float(r.get("net_put_premium") or 0), 0.0)
            except (TypeError, ValueError):
                pass

        total = calls + puts
        if total <= 0:
            return {}
        return {
            "bullish_ratio": calls / total,
            "net_call_premium": calls,
            "net_put_premium": puts,
        }

    async def get_net_ticker_premium(self, ticker: str, minutes: int = 60) -> Dict[str, Any]:
        """Compatibility shim over get_net_premium_ticks."""
        d = await self.get_net_premium_ticks(ticker, minutes)
        if not d:
            return {"net_direction": "NEUTRAL", "bullish_premium": 0, "bearish_premium": 0}
        c, p = d["net_calls"], d["net_puts"]
        return {
            "net_direction": "BULLISH" if c > p else ("BEARISH" if p > c else "NEUTRAL"),
            "bullish_premium": c,
            "bearish_premium": p,
        }

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
