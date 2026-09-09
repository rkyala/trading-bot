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
        """
        Fetch current price.

        Uses /stock/{t}/stock-state. The previous implementation called the
        bare /stock/{ticker}, which returns 404 "Route not found" — so this
        ALWAYS returned 0.0. Every alert would have read "Current: $0.00" and
        fallen through to "IN TARGET ZONE" (the price comparisons are all
        `price and ...`, so zero silently disables them), while still
        returning success because Discord accepted the post.
        """
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/stock/{ticker}/stock-state")
                if response.status_code == 200:
                    data = response.json().get("data", {}) or {}
                    px = self.safe_float(data.get("close") or data.get("last"))
                    if px > 0:
                        return px
                logger.warning(f"price unavailable for {ticker}: HTTP {response.status_code}")
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
            tickers = ["SPY", "QQQ", "IWM", "DIA"]

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


    # ------------------------------------------------------------------
    # Event-driven alerting.
    #
    # send_index_alerts() posts unconditionally. Called from the bot's 300s
    # cycle across 4 indices that is ~48 messages an hour, which trains the
    # reader to ignore the channel — and an ignored alert channel is worse
    # than none, because it looks like coverage.
    #
    # Instead: one snapshot on the first call of the day, then alerts only
    # when price CROSSES a level. A crossing is the tradeable event; sitting
    # between the same two walls for an hour is not news.
    # ------------------------------------------------------------------
    _zone_state: Dict[str, str] = {}
    _snapshot_day: Optional[str] = None

    @staticmethod
    def _zone(price: float, levels: Dict) -> str:
        """Which gamma zone the price occupies."""
        f = GEXDiscordAlerts.safe_float
        pw, gf, cw = f(levels.get("put_wall")), f(levels.get("gamma_flip")), f(levels.get("call_wall"))
        if not price:
            return "unknown"
        if pw and price < pw:
            return "below_put_wall"
        if cw and price > cw:
            return "above_call_wall"
        if gf and price < gf:
            return "below_flip"
        return "above_flip"

    async def check_crossings(self, tickers: List[str] = None) -> List[str]:
        """
        Poll indices; alert on the first call of the day and on zone changes.

        Returns the list of tickers alerted on.
        """
        # SPX/NDX have no price endpoint on this plan (/stock-state and /ohlc
        # both 422), so they could only ever post "$0.00". SPY/QQQ/IWM/DIA
        # serve both gex-levels and price, and are what the bot trades.
        tickers = tickers or ["SPY", "QQQ", "IWM", "DIA"]
        today = datetime.utcnow().strftime("%Y-%m-%d")
        first_of_day = self._snapshot_day != today
        alerted = []

        for t in tickers:
            try:
                levels = await self.get_gex_levels(t)
                if not levels or not (levels.get("put_wall") or levels.get("call_wall")):
                    continue
                price = await self.get_current_price(t)
                if not price:
                    logger.warning(f"GEX {t}: no price, skipping (would post $0.00)")
                    continue

                zone = self._zone(price, levels)
                prev = self._zone_state.get(t)
                self._zone_state[t] = zone

                if not first_of_day and (prev is None or prev == zone):
                    continue    # nothing changed — stay quiet

                embed = self.format_gex_embed(t, price, levels)
                if prev and prev != zone:
                    embed["title"] = f"⚡ GEX ZONE CHANGE — {t}"
                    embed["description"] = (
                        f"**{prev.replace('_',' ')} → {zone.replace('_',' ')}**\n"
                        + embed["description"]
                    )
                if await self.send_discord_alert(t, embed):
                    alerted.append(t)
            except Exception as e:
                logger.error(f"GEX crossing check failed for {t}: {e}")

        if first_of_day:
            self._snapshot_day = today
        return alerted


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
