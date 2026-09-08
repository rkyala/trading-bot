"""
Enhanced UW Data Client
Add market-tide, greeks, insider trades, IV percentiles
"""

import asyncio
import httpx
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

UW_API_KEY = ""
BASE_URL = "https://api.unusualwhales.com/api"


class EnhancedUWDataClient:
    """Fetch high-value institutional data from Unusual Whales"""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self.base_url = BASE_URL

    async def get_market_tide(self) -> Dict:
        """
        Fetch market-wide flow sentiment (Gate 3 macro context)

        Returns:
          {
            "bullish_count": int,
            "bearish_count": int,
            "net_direction": str,  # BULLISH | BEARISH | NEUTRAL
            "ratio": float,         # bullish / total
            "timestamp": str
          }
        """
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/market/market-tide")
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    bullish = int(data.get("bullish_count", 0))
                    bearish = int(data.get("bearish_count", 0))
                    total = bullish + bearish or 1

                    return {
                        "bullish_count": bullish,
                        "bearish_count": bearish,
                        "ratio": bullish / total,
                        "net_direction": "BULLISH" if bullish > bearish else "BEARISH" if bearish > bullish else "NEUTRAL",
                        "timestamp": data.get("timestamp")
                    }
            except Exception as e:
                logger.error(f"Market tide fetch error: {e}")

        return {"ratio": 0.5, "net_direction": "NEUTRAL"}

    async def get_greeks(self, ticker: str) -> Dict:
        """
        Fetch Greeks per strike (entry/exit confluence)

        Returns:
          {
            "ticker": str,
            "strikes": [
              {
                "strike": float,
                "delta": float,
                "gamma": float,
                "theta": float,
                "vega": float,
                "iv": float
              },
              ...
            ]
          }
        """
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/stock/{ticker}/greeks")
                if response.status_code == 200:
                    data = response.json().get("data", [])

                    strikes = []
                    for item in data[:10]:  # Top 10 strikes
                        strikes.append({
                            "strike": float(item.get("strike", 0)),
                            "delta": float(item.get("delta", 0)),
                            "gamma": float(item.get("gamma", 0)),
                            "theta": float(item.get("theta", 0)),
                            "vega": float(item.get("vega", 0)),
                            "iv": float(item.get("iv", 0))
                        })

                    return {
                        "ticker": ticker,
                        "strikes": strikes
                    }
            except Exception as e:
                logger.error(f"Greeks fetch error for {ticker}: {e}")

        return {"ticker": ticker, "strikes": []}

    async def get_insider_transactions(self, days_back: int = 1) -> Dict[str, List]:
        """
        Fetch insider trading activity (conviction filter)

        Returns:
          {
            "buys": [
              {"ticker": str, "name": str, "shares": int, "value": float},
              ...
            ],
            "sells": [...]
          }
        """
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/insider/transactions")
                if response.status_code == 200:
                    data = response.json().get("data", [])

                    buys = []
                    sells = []

                    for tx in data[:20]:  # Last 20 transactions
                        if tx.get("transaction_type") == "BUY":
                            buys.append({
                                "ticker": tx.get("symbol"),
                                "name": tx.get("name"),
                                "shares": int(tx.get("shares", 0)),
                                "value": float(tx.get("value", 0))
                            })
                        else:
                            sells.append({
                                "ticker": tx.get("symbol"),
                                "name": tx.get("name"),
                                "shares": int(tx.get("shares", 0)),
                                "value": float(tx.get("value", 0))
                            })

                    return {"buys": buys, "sells": sells}
            except Exception as e:
                logger.error(f"Insider transactions fetch error: {e}")

        return {"buys": [], "sells": []}

    async def get_iv_percentile(self, ticker: str) -> Dict:
        """
        Fetch IV percentile and context (overbought/oversold)

        Returns:
          {
            "ticker": str,
            "current_iv": float,
            "iv_percentile": float,      # 0-100
            "realized_vol": float,
            "status": "CHEAP" | "FAIR" | "EXPENSIVE"
          }
        """
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/stock/{ticker}/interpolated-iv")
                if response.status_code == 200:
                    data = response.json().get("data", {})

                    iv_pct = float(data.get("iv_percentile", 50))

                    # Determine status
                    if iv_pct < 25:
                        status = "CHEAP"
                    elif iv_pct > 75:
                        status = "EXPENSIVE"
                    else:
                        status = "FAIR"

                    return {
                        "ticker": ticker,
                        "current_iv": float(data.get("current_iv", 0)),
                        "iv_percentile": iv_pct,
                        "realized_vol": float(data.get("realized_vol", 0)),
                        "status": status
                    }
            except Exception as e:
                logger.error(f"IV percentile fetch error for {ticker}: {e}")

        return {
            "ticker": ticker,
            "current_iv": 0,
            "iv_percentile": 50,
            "realized_vol": 0,
            "status": "FAIR"
        }


async def main():
    """Test enhanced data client"""
    client = EnhancedUWDataClient(api_key="test")

    print("Testing Enhanced UW Data Client")
    print("=" * 60)
    print()

    # Test market tide
    print("1. Market Tide (Gate 3)")
    tide = await client.get_market_tide()
    print(f"   Direction: {tide['net_direction']}")
    print(f"   Bullish Ratio: {tide['ratio']:.1%}")
    print()

    # Test greeks
    print("2. Greeks (Strike-Level)")
    greeks = await client.get_greeks("NVDA")
    if greeks["strikes"]:
        print(f"   {len(greeks['strikes'])} strikes fetched")
        print(f"   Example: Strike {greeks['strikes'][0]['strike']}")
    print()

    # Test insider
    print("3. Insider Transactions")
    insiders = await client.get_insider_transactions()
    print(f"   Buys: {len(insiders['buys'])}")
    print(f"   Sells: {len(insiders['sells'])}")
    print()

    # Test IV
    print("4. IV Percentile")
    iv = await client.get_iv_percentile("SPY")
    print(f"   IV Status: {iv['status']}")
    print(f"   IV Percentile: {iv['iv_percentile']:.0f}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
