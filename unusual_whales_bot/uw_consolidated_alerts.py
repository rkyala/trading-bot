"""
Consolidated Daily Fundamentals Alerts
Single daily summary: earnings risk, insider activity, analyst changes
Destination: UW Discord channel
"""

import asyncio
import httpx
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

UW_API_KEY = os.getenv("UW_API_KEY", "")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "")
BASE_URL = "https://api.unusualwhales.com/api"


class ConsolidatedAlerts:
    """Send daily consolidated fundamentals alerts"""

    def __init__(self, api_key: str = None, webhook_url: str = None):
        self.api_key = api_key or UW_API_KEY
        self.webhook_url = webhook_url or DISCORD_WEBHOOK
        self.base_url = BASE_URL

    async def get_earnings_calendar(self, days_ahead: int = 7) -> List[Dict]:
        """Fetch upcoming earnings"""
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/earnings/calendar")
                if response.status_code == 200:
                    data = response.json().get("data", [])
                    # Filter to next N days
                    upcoming = []
                    for item in data[:10]:  # Top 10 upcoming
                        upcoming.append({
                            "ticker": item.get("symbol"),
                            "date": item.get("earnings_date"),
                            "time": item.get("earnings_time"),
                            "iv_rank": item.get("iv_rank", 0),
                            "implied_move": item.get("implied_move", 0)
                        })
                    return upcoming
            except Exception as e:
                logger.error(f"Earnings fetch error: {e}")
        return []

    async def get_insider_activity(self, days_back: int = 1) -> Dict[str, List]:
        """Fetch insider buy/sell activity"""
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                # Note: This endpoint may vary; adjust as needed
                response = await client.get(f"{self.base_url}/insiders/activity")
                if response.status_code == 200:
                    data = response.json().get("data", [])
                    buys = [item for item in data if item.get("side") == "BUY"][:5]
                    sells = [item for item in data if item.get("side") == "SELL"][:5]
                    return {"buys": buys, "sells": sells}
            except Exception as e:
                logger.error(f"Insider activity fetch error: {e}")
        return {"buys": [], "sells": []}

    async def get_analyst_changes(self) -> Dict[str, List]:
        """Fetch analyst rating changes"""
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=10.0
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/analysts/changes")
                if response.status_code == 200:
                    data = response.json().get("data", [])
                    upgrades = [item for item in data if item.get("change") == "UPGRADE"][:5]
                    downgrades = [item for item in data if item.get("change") == "DOWNGRADE"][:5]
                    return {"upgrades": upgrades, "downgrades": downgrades}
            except Exception as e:
                logger.error(f"Analyst changes fetch error: {e}")
        return {"upgrades": [], "downgrades": []}

    def format_consolidated_embed(self, earnings: List, insiders: Dict, analysts: Dict) -> Dict:
        """Format consolidated daily summary as Discord embed"""

        # Format earnings
        earnings_text = ""
        if earnings:
            for item in earnings[:5]:  # Top 5
                ticker = item.get("ticker", "?")
                implied = item.get("implied_move", 0)
                earnings_text += f"• **{ticker}**: ±{implied:.1f}% move\n"
        else:
            earnings_text = "No major earnings this week\n"

        # Format insider activity
        insider_text = ""
        buys = insiders.get("buys", [])
        sells = insiders.get("sells", [])

        if buys:
            insider_text += "**Buys:**\n"
            for buy in buys[:3]:
                insider_text += f"• {buy.get('ticker')} - {buy.get('shares', 0)} shares\n"

        if sells:
            insider_text += "**Sells:**\n"
            for sell in sells[:3]:
                insider_text += f"• {sell.get('ticker')} - {sell.get('shares', 0)} shares\n"

        if not insider_text:
            insider_text = "No significant insider activity\n"

        # Format analyst changes
        analyst_text = ""
        upgrades = analysts.get("upgrades", [])
        downgrades = analysts.get("downgrades", [])

        if upgrades:
            analyst_text += "**Upgrades:**\n"
            for up in upgrades[:3]:
                analyst_text += f"• {up.get('ticker')} - {up.get('firm')}\n"

        if downgrades:
            analyst_text += "**Downgrades:**\n"
            for down in downgrades[:3]:
                analyst_text += f"• {down.get('ticker')} - {down.get('firm')}\n"

        if not analyst_text:
            analyst_text = "No rating changes\n"

        # Build embed
        description = f"""
**📅 EARNINGS RISK THIS WEEK**
{earnings_text}

**👤 INSIDER ACTIVITY (Last 24h)**
{insider_text}

**📊 ANALYST CHANGES**
{analyst_text}

**⏱ Summary Updated:** {datetime.now().strftime('%I:%M %p %Z')}
"""

        embed = {
            "title": "📊 Daily Fundamentals Alert",
            "description": description,
            "color": 0x3498db,  # Blue
            "footer": {
                "text": "UW Consolidated | Fundamentals Analysis",
                "icon_url": "https://api.unusualwhales.com/public/logo.png"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        return embed

    async def send_discord_alert(self, embed: Dict) -> bool:
        """Send alert to Discord"""
        if not self.webhook_url:
            logger.warning("Discord webhook not configured")
            return False

        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "username": "UW Fundamentals",
                "avatar_url": "https://api.unusualwhales.com/public/logo.png",
                "embeds": [embed]
            }
            try:
                response = await client.post(self.webhook_url, json=payload)
                if response.status_code == 204:
                    logger.info("Consolidated alert sent to Discord")
                    return True
                else:
                    logger.warning(f"Discord send failed: {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"Discord send error: {e}")
                return False

    async def send_daily_consolidated(self) -> bool:
        """Send consolidated daily alert"""
        logger.info("Fetching fundamentals data...")

        # Fetch all data
        earnings = await self.get_earnings_calendar(days_ahead=7)
        insiders = await self.get_insider_activity(days_back=1)
        analysts = await self.get_analyst_changes()

        # Format and send
        embed = self.format_consolidated_embed(earnings, insiders, analysts)
        return await self.send_discord_alert(embed)


async def main():
    """Send consolidated alert"""
    alerts = ConsolidatedAlerts()
    success = await alerts.send_daily_consolidated()

    if success:
        print("\n" + "=" * 60)
        print("✅ CONSOLIDATED ALERT SENT")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("⚠️  ALERT FAILED")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
