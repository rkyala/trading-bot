"""
Discord GEX Support/Resistance Alerts
Sends alerts for major indices: SPX, SPY, NDX, IWM
"""

import asyncio
import httpx
import os
import logging
from datetime import datetime
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

UW_API_KEY = os.getenv("UW_API_KEY", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")

BASE_URL = "https://api.unusualwhales.com/api"


class GEXDiscordAlerts:
    """Send Discord alerts for GEX support/resistance levels"""

    def __init__(self, api_key: str = None, webhook_url: str = None):
        self.api_key = api_key or UW_API_KEY
        self.webhook_url = webhook_url or DISCORD_WEBHOOK
        self.base_url = BASE_URL

    async def get_gex_levels(self, ticker: str) -> Optional[Dict]:
        """Fetch GEX levels for ticker"""
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/stock/{ticker}/gex-levels")
                if response.status_code == 200:
                    return response.json().get("data", {})
            except Exception as e:
                logger.error(f"GEX levels fetch error for {ticker}: {e}")
        return None

    async def get_current_price(self, ticker: str) -> float:
        """Fetch current price for ticker"""
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/stock/{ticker}")
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    return float(data.get("last", 0) or data.get("price", 0))
            except Exception as e:
                logger.error(f"Price fetch error for {ticker}: {e}")
        return 0.0

    @staticmethod
    def safe_float(val) -> float:
        """Safely convert to float"""
        if val is None:
            return 0.0
        if isinstance(val, str):
            try:
                return float(val)
            except:
                return 0.0
        return float(val)

    def format_gex_embed(self, ticker: str, price: float, levels: Dict) -> Dict:
        """Format GEX levels as Discord embed"""

        put_wall = self.safe_float(levels.get("put_wall"))
        gamma_flip = self.safe_float(levels.get("gamma_flip"))
        gamma_magnet = self.safe_float(levels.get("gamma_magnet"))
        call_wall = self.safe_float(levels.get("call_wall"))

        # Determine position relative to levels
        if price and put_wall and price < put_wall:
            status = "🔴 BELOW PUT WALL (BREAKDOWN)"
            color = 0xe74c3c  # Red
        elif price and gamma_flip and price < gamma_flip:
            status = "🟡 CONSOLIDATING (Below Flip)"
            color = 0xf39c12  # Orange
        elif price and call_wall and price > call_wall:
            status = "🟢 ABOVE CALL WALL (BREAKOUT)"
            color = 0x2ecc71  # Green
        else:
            status = "🟢 IN TARGET ZONE"
            color = 0x1abc9c  # Teal

        description = f"""
**Current: ${price:.2f}** {status}

**Support/Resistance:**
🔴 **PUT WALL**: ${put_wall:.2f}
🟡 **GAMMA FLIP**: ${gamma_flip:.2f}
⚪ **GAMMA MAGNET**: ${gamma_magnet:.2f}
🟢 **CALL WALL**: ${call_wall:.2f}
"""

        # Add distance info
        if price > 0:
            distance_to_flip = ((gamma_flip - price) / price * 100) if price else 0
            distance_to_call = ((call_wall - price) / price * 100) if price else 0

            description += f"""
**Distance to Flip**: {distance_to_flip:+.2f}%
**Distance to Call Wall**: {distance_to_call:+.2f}%
"""

        embed = {
            "title": f"GEX Levels - {ticker}",
            "description": description,
            "color": color,
            "footer": {
                "text": "Gamma Exposure | Unusual Whales",
                "icon_url": "https://api.unusualwhales.com/public/logo.png"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        return embed

    async def send_discord_alert(self, ticker: str, embed: Dict) -> bool:
        """Send alert to Discord"""
        if not self.webhook_url:
            logger.warning(f"Discord webhook not configured, skipping {ticker}")
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "username": "GEX Levels Monitor",
                "avatar_url": "https://api.unusualwhales.com/public/logo.png",
                "embeds": [embed]
            }
            try:
                response = await client.post(self.webhook_url, json=payload)
                if response.status_code == 204:
                    logger.info(f"Discord alert sent for {ticker}")
                    return True
                else:
                    logger.warning(f"Discord send failed for {ticker}: {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"Discord send error for {ticker}: {e}")
                return False

    async def send_index_alerts(self, tickers: List[str] = None) -> Dict[str, bool]:
        """Send alerts for indices"""
        if tickers is None:
            tickers = ["SPX", "SPY", "NDX", "IWM"]

        results = {}

        for ticker in tickers:
            try:
                logger.info(f"Fetching GEX levels for {ticker}")
                price = await self.get_current_price(ticker)
                levels = await self.get_gex_levels(ticker)

                if levels and (levels.get("put_wall") or levels.get("call_wall")):
                    embed = self.format_gex_embed(ticker, price, levels)
                    success = await self.send_discord_alert(ticker, embed)
                    results[ticker] = success
                else:
                    logger.warning(f"No GEX levels data for {ticker}")
                    results[ticker] = False

            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                results[ticker] = False

        return results


async def main():
    """Send alerts for all major indices"""
    alerts = GEXDiscordAlerts()
    results = await alerts.send_index_alerts()

    print("\n" + "=" * 60)
    print("GEX DISCORD ALERTS - RESULTS")
    print("=" * 60)
    for ticker, success in results.items():
        status = "✅" if success else "⚠️"
        print(f"{status} {ticker}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
