"""
GEX + Dark Pool Data Client

Real-time institutional conviction signals:
- Greek Exposure (GEX): Gamma regime (volatility amplification/suppression)
- Dark Pool Volume: Institutional accumulation/distribution

Integrates with Phase 1 Gate 5.5 (GEX-Dark Pool Confluence)
"""

import logging
import asyncio
from typing import Dict, Optional, Any
import httpx

logger = logging.getLogger(__name__)


class GEXDarkPoolClient:
    """Fetch GEX and dark pool data from Unusual Whales API"""

    def __init__(self, api_key: str, base_url: str = "https://api.unusualwhales.com/api"):
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
        self.stats = {
            "gex_fetches": 0,
            "darkpool_fetches": 0,
            "errors": 0,
        }

    async def _get_session(self) -> httpx.AsyncClient:
        """Get or create async HTTP session"""
        if self.session is None:
            self.session = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10.0
            )
        return self.session

    async def get_gex_exposure(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Fetch Greek Exposure (GEX) for ticker.

        Returns gamma exposure (positive = volatility suppressed = bullish)

        Args:
            ticker: Stock ticker (e.g., "NVDA")

        Returns:
            {
                "gamma_per_one_percent_move_oi": float,  # Positive = bullish GEX
                "gamma_per_one_percent_move": float,
                "delta_adjusted_exposure": float,
                "vega_exposure": float,
                "theta_exposure": float
            }
        """
        try:
            self.stats["gex_fetches"] += 1

            session = await self._get_session()
            url = f"{self.base_url}/stock/{ticker}/greek-exposure"

            response = await session.get(url)

            if response.status_code != 200:
                logger.warning(f"GEX fetch error for {ticker}: {response.status_code}")
                return None

            json_data = response.json()
            data = json_data.get("data", {})

            # Handle list response (API may return array)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            elif not isinstance(data, dict):
                logger.warning(f"Unexpected GEX response format for {ticker}")
                return None

            # Extract key GEX metric
            gamma = data.get("gamma_per_one_percent_move_oi", 0)

            return {
                "ticker": ticker,
                "gamma_per_one_percent_move_oi": gamma,
                "gamma_per_one_percent_move": data.get("gamma_per_one_percent_move", 0),
                "delta_adjusted_exposure": data.get("delta_adjusted_exposure", 0),
                "vega_exposure": data.get("vega_exposure", 0),
                "theta_exposure": data.get("theta_exposure", 0),
                "gex_regime": "BULLISH" if gamma > 0 else "BEARISH" if gamma < -10_000_000_000 else "NEUTRAL"
            }

        except Exception as e:
            logger.error(f"GEX fetch error for {ticker}: {e}")
            self.stats["errors"] += 1
            return None

    async def get_gex_levels(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Fetch GEX Price Levels for ticker.

        Key gamma-exposure (GEX) price levels: support/resistance zones, gamma magnet, zero-gamma flip.

        Args:
            ticker: Stock ticker (e.g., "NVDA")

        Returns:
            {
                "call_wall": float,           # Resistance (gamma above spot)
                "put_wall": float,            # Support (gamma below spot)
                "gamma_magnet": float,        # Strongest pin level
                "gamma_flip": float,          # Zero-gamma crossing (equilibrium)
                "nearby_flips": [float, ...], # Multiple zero-gamma levels
                "source": str                 # "vol" or "oi"
            }
        """
        try:
            self.stats["gex_fetches"] += 1

            session = await self._get_session()
            url = f"{self.base_url}/stock/{ticker}/gex-levels"

            response = await session.get(url)

            if response.status_code != 200:
                logger.warning(f"GEX levels fetch error for {ticker}: {response.status_code}")
                return None

            data = response.json().get("data", {})

            if not isinstance(data, dict):
                logger.warning(f"Unexpected GEX levels response format for {ticker}")
                return None

            return {
                "ticker": ticker,
                "call_wall": data.get("call_wall"),       # Price resistance
                "put_wall": data.get("put_wall"),         # Price support
                "gamma_magnet": data.get("gamma_magnet"), # Strongest pin
                "gamma_flip": data.get("gamma_flip"),     # Equilibrium
                "nearby_flips": data.get("nearby_flips", []),  # Multiple flips
                "source": data.get("source", "vol"),
                "date": data.get("date"),
                "time": data.get("time")
            }

        except Exception as e:
            logger.error(f"GEX levels fetch error for {ticker}: {e}")
            self.stats["errors"] += 1
            return None

    async def get_dark_pool_volume(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Fetch dark pool trading activity for ticker.

        Shows institutional accumulation (BUY) or distribution (SELL)

        Args:
            ticker: Stock ticker (e.g., "NVDA")

        Returns:
            {
                "dark_pool_notional": float,  # $ volume in dark pools
                "dark_pool_volume": int,       # Share volume
                "dark_pool_pct": float,        # % of total volume
                "direction": "BUY" | "SELL" | "NEUTRAL",  # Based on bid-ask
                "latest_price": float,
                "latest_time": str
            }
        """
        try:
            self.stats["darkpool_fetches"] += 1

            session = await self._get_session()
            url = f"{self.base_url}/darkpool/{ticker}"

            response = await session.get(url)

            if response.status_code != 200:
                logger.warning(f"Dark pool fetch error for {ticker}: {response.status_code}")
                return None

            data = response.json().get("data", {})

            # Most recent dark pool trade
            if isinstance(data, list) and len(data) > 0:
                trade = data[0]
            else:
                trade = data

            notional = float(trade.get("notional_value", 0))
            volume = int(trade.get("volume", 0))

            return {
                "ticker": ticker,
                "dark_pool_notional": notional,
                "dark_pool_volume": volume,
                "dark_pool_pct": float(trade.get("percent_of_volume", 0)),
                "direction": trade.get("side", "NEUTRAL").upper(),
                "latest_price": float(trade.get("price", 0)),
                "latest_time": trade.get("time", ""),
                "bid_ask_imbalance": trade.get("bid_ask_imbalance", 0)
            }

        except Exception as e:
            logger.error(f"Dark pool fetch error for {ticker}: {e}")
            self.stats["errors"] += 1
            return None

    async def close(self):
        """Close async session"""
        if self.session:
            await self.session.aclose()
            self.session = None

    def __del__(self):
        """Cleanup on delete"""
        if self.session:
            try:
                asyncio.run(self.close())
            except:
                pass
