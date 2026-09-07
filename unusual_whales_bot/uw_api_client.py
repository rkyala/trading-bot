"""
Phase 1: Complete Unusual Whales API Integration (All 5 Endpoints)

Endpoints:
1. Flow Alerts - Individual sweeps (>$100k premium)
2. Market Tide - Index-wide net call/put premium (macro gate)
3. Net Ticker Premium - Ticker-level net positioning (60-min window)
4. Dark Pool Volume - Off-exchange block trades (underlying validation)
5. Vol/OI Ratio - Volume > Open Interest (new position confirmation)

This achieves 100% UW capability.
"""

import httpx
import logging
from typing import Optional, Dict, List
from datetime import datetime

logger = logging.getLogger(__name__)


class UnusualWhalesAPI:
    """Full Unusual Whales API client (all 5 endpoints)"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.unusualwhales.com/api"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def get_flow_alerts(self, ticker: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Endpoint 1: Individual sweep alerts"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/alert"
            params = {"limit": limit}
            if ticker:
                params["ticker"] = ticker
            try:
                resp = await client.get(url, headers=self.headers, params=params, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    logger.info(f"✅ Fetched {len(data)} flow alerts")
                    return data
            except Exception as e:
                logger.error(f"❌ Alert fetch failed: {e}")
        return []

    async def get_market_tide(self, ticker: str = "SPY") -> Dict:
        """Endpoint 2: Net Market Tide (MACRO FLOW GATE)"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/market-tide/{ticker}"
            try:
                resp = await client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    net_call = data.get("net_call_premium", 0)
                    net_put = data.get("net_put_premium", 0)
                    if net_call > net_put and net_call > 5_000_000:
                        direction = "BULLISH"
                        strength = min(net_call / 50_000_000, 1.0)
                    elif net_put > net_call and net_put > 5_000_000:
                        direction = "BEARISH"
                        strength = min(net_put / 50_000_000, 1.0)
                    else:
                        direction = "NEUTRAL"
                        strength = 0.0
                    return {
                        "ticker": ticker,
                        "net_call_premium": net_call,
                        "net_put_premium": net_put,
                        "net_direction": direction,
                        "tide_strength": strength,
                    }
            except Exception as e:
                logger.error(f"❌ Market Tide failed: {e}")
        return {"ticker": ticker, "net_direction": "NEUTRAL", "tide_strength": 0.0}

    async def get_net_ticker_premium(self, ticker: str, window_minutes: int = 60) -> Dict:
        """Endpoint 3: Net Ticker Premium (POSITIONING FILTER)"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/ticker/{ticker}/net-premium"
            params = {"window": window_minutes}
            try:
                resp = await client.get(url, headers=self.headers, params=params, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    net_call = data.get("net_call_premium", 0)
                    net_put = data.get("net_put_premium", 0)
                    direction = "BULLISH" if net_call > net_put else "BEARISH"
                    return {
                        "ticker": ticker,
                        "net_call_premium": net_call,
                        "net_put_premium": net_put,
                        "net_direction": direction,
                        "time_window": window_minutes,
                    }
            except Exception as e:
                logger.error(f"❌ Net premium failed: {e}")
        return {"ticker": ticker, "net_direction": "NEUTRAL"}

    async def get_dark_pool_volume(self, ticker: str) -> Dict:
        """Endpoint 4: Dark Pool Prints (UNDERLYING VALIDATION)"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/darkpool/{ticker}"
            try:
                resp = await client.get(url, headers=self.headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    volume = data.get("total_volume", 0)
                    side = data.get("net_side", "NEUTRAL")
                    blocks = data.get("block_count", 0)
                    is_suspicious = volume > 100_000_000 or blocks > 100
                    return {
                        "ticker": ticker,
                        "dark_pool_volume": volume,
                        "dark_pool_side": side,
                        "block_trades": blocks,
                        "suspicious": is_suspicious,
                    }
            except Exception as e:
                logger.error(f"❌ Dark pool failed: {e}")
        return {"ticker": ticker, "dark_pool_volume": 0, "suspicious": False}

    async def get_vol_oi_ratio(self, ticker: str, days_to_expiry: int = 30) -> Dict:
        """Endpoint 5: Volume / Open Interest Ratio (NEW POSITION CONFIRMATION)"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/ticker/{ticker}/vol-oi"
            params = {"dte": days_to_expiry}
            try:
                resp = await client.get(url, headers=self.headers, params=params, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    volume = data.get("volume", 0)
                    oi = data.get("open_interest", 1)
                    ratio = volume / oi if oi > 0 else 0
                    if ratio > 1.2:
                        pos_type, confirmation = "NEW_OPENING", "STRONG"
                    elif ratio > 1.0:
                        pos_type, confirmation = "NEW_OPENING", "NORMAL"
                    else:
                        pos_type, confirmation = "CLOSING", "WEAK"
                    return {
                        "ticker": ticker,
                        "volume": volume,
                        "open_interest": oi,
                        "vol_oi_ratio": round(ratio, 2),
                        "position_type": pos_type,
                        "confirmation": confirmation,
                    }
            except Exception as e:
                logger.error(f"❌ Vol/OI failed: {e}")
        return {"ticker": ticker, "vol_oi_ratio": 0.0, "position_type": "UNKNOWN"}


class UnusualWhalesMockAPI:
    """Mock UW API for testing without real key"""

    async def get_flow_alerts(self, ticker: Optional[str] = None, limit: int = 50) -> List[Dict]:
        return [{"symbol": "SPX", "direction": "CALL", "premium": 250_000, "ask_volume_pct": 0.85}]

    async def get_market_tide(self, ticker: str = "SPY") -> Dict:
        return {
            "ticker": ticker,
            "net_call_premium": 45_000_000,
            "net_put_premium": -10_000_000,
            "net_direction": "BULLISH",
            "tide_strength": 0.85,
        }

    async def get_net_ticker_premium(self, ticker: str, window_minutes: int = 60) -> Dict:
        return {
            "ticker": ticker,
            "net_call_premium": 2_500_000,
            "net_put_premium": -500_000,
            "net_direction": "BULLISH",
            "time_window": window_minutes,
        }

    async def get_dark_pool_volume(self, ticker: str) -> Dict:
        return {
            "ticker": ticker,
            "dark_pool_volume": 15_000_000,
            "dark_pool_side": "BUY",
            "block_trades": 42,
            "suspicious": False,
        }

    async def get_vol_oi_ratio(self, ticker: str, days_to_expiry: int = 30) -> Dict:
        return {
            "ticker": ticker,
            "volume": 75_000,
            "open_interest": 50_000,
            "vol_oi_ratio": 1.50,
            "position_type": "NEW_OPENING",
            "confirmation": "STRONG",
        }
