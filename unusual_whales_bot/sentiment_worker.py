"""
Phase 3B: Trading-Hero Sentiment Service (Sidecar)

Background async worker that:
1. Polls financial news APIs (NewsAPI, Finnhub, etc.)
2. Runs FinBERT sentiment analysis
3. Caches results in Redis
4. Maintains ticker-level sentiment consensus

Run independently:
    python sentiment_worker.py

Or integrate into supervisor (systemd, docker, etc.)

CRITICAL: This is a TEMPLATE. Production deployment requires:
- NewsAPI key (https://newsapi.org)
- Finnhub key (https://finnhub.io)
- Redis instance running
- Error handling for rate limits / network
"""

import asyncio
import logging
import time
import requests
import os
from typing import List, Dict, Optional
from datetime import datetime, timedelta, time as time_type

# Optional: Only import if running standalone
try:
    from transformers import pipeline
    FINBERT_AVAILABLE = True
except ImportError:
    FINBERT_AVAILABLE = False
    logging.warning("⚠️ transformers not installed. Sentiment analysis disabled.")

# Local imports
try:
    from uw_redis_config import get_redis_config, init_redis
except ImportError:
    logging.warning("⚠️ uw_redis_config not found. Redis integration disabled.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class TradingHeroSentimentService:
    """
    Background sentiment analysis service.

    Polls news APIs → FinBERT analysis → Redis cache → Discord alerts (hourly)
    """

    def __init__(self, use_finbert: bool = True, discord_webhook: Optional[str] = None):
        self.use_finbert = use_finbert and FINBERT_AVAILABLE
        self.classifier = None
        self.redis_config = None
        self.discord_webhook = discord_webhook or os.getenv("DISCORD_WEBHOOK_URL")
        self.tickers = ["SPX", "NDX", "RUT", "SPY", "QQQ", "IWM"]
        self.last_discord_alert = None
        self.stats = {
            "articles_analyzed": 0,
            "cache_updates": 0,
            "errors": 0,
            "discord_alerts_sent": 0,
            "startup_time": datetime.now(),
        }

        if self.use_finbert:
            self._init_finbert()

        try:
            self.redis_config = get_redis_config()
        except Exception as e:
            logger.warning(f"Redis init failed: {e}")

    def _init_finbert(self):
        """Initialize FinBERT model"""
        try:
            logger.info("📥 Loading FinBERT model (may take 30s on first run)...")
            self.classifier = pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                return_all_scores=False,
            )
            logger.info("✅ FinBERT loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load FinBERT: {e}")
            logger.warning("📌 Falling back to VADER sentiment (lighter, faster)")
            self.use_finbert = False

    def analyze_headline(self, text: str) -> str:
        """
        Analyze sentiment of a single headline.

        Returns: "positive", "negative", or "neutral"
        """
        if not text or len(text) < 10:
            return "neutral"

        try:
            if self.classifier is not None:
                result = self.classifier(text[:512])[0]  # Truncate long texts
                label = result["label"].lower()
                score = result.get("score", 0)

                # Map FinBERT output (positive/negative/neutral)
                if label == "positive":
                    return "positive"
                elif label == "negative":
                    return "negative"
                else:
                    return "neutral"
            else:
                # Fallback: simple keyword matching (VADER-lite)
                text_lower = text.lower()
                positive_words = [
                    "surge",
                    "rally",
                    "bull",
                    "gain",
                    "rise",
                    "jump",
                    "growth",
                    "beat",
                    "strong",
                ]
                negative_words = [
                    "plunge",
                    "bear",
                    "fall",
                    "drop",
                    "loss",
                    "crash",
                    "decline",
                    "miss",
                    "weak",
                ]

                pos_count = sum(1 for w in positive_words if w in text_lower)
                neg_count = sum(1 for w in negative_words if w in text_lower)

                if pos_count > neg_count:
                    return "positive"
                elif neg_count > pos_count:
                    return "negative"
                else:
                    return "neutral"

        except Exception as e:
            logger.warning(f"Sentiment analysis error: {e}")
            return "neutral"

    def update_ticker_sentiment(
        self, ticker: str, headlines: List[str]
    ) -> Optional[str]:
        """
        Analyze multiple headlines and cache consensus sentiment.

        Returns: consensus sentiment ("positive", "negative", "neutral")
        """
        if not headlines:
            # No news = neutral
            if self.redis_config:
                self.redis_config.set_sentiment(ticker, "neutral")
            return "neutral"

        # Analyze all headlines
        sentiments = [self.analyze_headline(h) for h in headlines]
        self.stats["articles_analyzed"] += len(sentiments)

        # Calculate consensus (weighted by recency if available)
        pos_count = sentiments.count("positive")
        neg_count = sentiments.count("negative")
        neu_count = sentiments.count("neutral")

        # Majority rules
        if pos_count > max(neg_count, neu_count):
            consensus = "positive"
        elif neg_count > max(pos_count, neu_count):
            consensus = "negative"
        else:
            consensus = "neutral"

        # Cache result
        if self.redis_config:
            self.redis_config.set_sentiment(ticker, consensus, ttl=900)
            self.stats["cache_updates"] += 1

        logger.info(
            f"📊 {ticker}: {consensus.upper()} (pos={pos_count}, neg={neg_count}, neu={neu_count})"
        )
        return consensus

    async def poll_news(self, ticker: str) -> List[str]:
        """
        Fetch latest headlines for ticker.

        TEMPLATE: Integrate with NewsAPI, Finnhub, or custom RSS feed.
        For now, returns mock data.

        In production:
            - Use NewsAPI: requests.get(f"https://newsapi.org/v2/everything?q={ticker}&apiKey=KEY")
            - Use Finnhub: requests.get(f"https://finnhub.io/api/v1/news?symbol={ticker}&token=KEY")
            - Parse RSS feeds for financial sites
        """
        # MOCK: Return sample headlines for testing
        mock_headlines = {
            "SPX": [
                "Federal Reserve signals rate cuts as inflation continues to cool.",
                "S&P 500 reaches new all-time high on strong earnings.",
                "Market volatility subdued ahead of jobs data.",
            ],
            "NDX": [
                "Tech stocks rally on strong semiconductor guidance.",
                "Nvidia reports record AI chip demand.",
                "Cloud computing earnings beat expectations.",
            ],
            "RUT": [
                "Small-cap stocks lag as credit market tightens.",
                "Regional banks show signs of stress.",
                "Mid-market M&A activity slows.",
            ],
        }

        # In production, this would be async with newsapi / finnhub
        headlines = mock_headlines.get(ticker, [])
        logger.debug(f"🔍 Fetched {len(headlines)} headlines for {ticker}")
        return headlines

    async def run_cycle(self):
        """Single sentiment update cycle (+ hourly Discord alert)"""
        logger.info("🔄 Sentiment update cycle starting...")

        for ticker in self.tickers:
            try:
                # Fetch news
                headlines = await self.poll_news(ticker)

                # Update sentiment
                sentiment = self.update_ticker_sentiment(ticker, headlines)

                await asyncio.sleep(0.5)  # Rate limit

            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}")
                self.stats["errors"] += 1

        # Send hourly Discord briefing (if trading hours + 1h elapsed)
        await self.send_hourly_sentiment_briefing()

        logger.info("✅ Sentiment update cycle complete")

    async def run_loop(self, interval_seconds: int = 60):
        """
        Main loop: Run sentiment updates every N seconds.

        Typical interval: 60s (balance freshness vs. API limits)
        """
        logger.info(
            f"🚀 Sentiment worker starting (update every {interval_seconds}s)..."
        )
        cycle_count = 0

        try:
            while True:
                cycle_count += 1
                logger.info(f"\n[Cycle {cycle_count}] Starting sentiment update...")

                await self.run_cycle()

                await asyncio.sleep(interval_seconds)

        except KeyboardInterrupt:
            logger.info("⏸️ Sentiment worker stopped by user")
            self.log_stats()

    def _send_discord_alert(self, title: str, content: str, color: int = 3447003):
        """
        Send formatted alert to Discord webhook.

        Args:
            title: Alert title
            content: Alert content (markdown)
            color: Embed color (0-16777215)
                3447003 = blue (neutral)
                65280 = green (positive)
                16711680 = red (negative)
                16776960 = yellow (warning)
        """
        if not self.discord_webhook:
            return False

        try:
            payload = {
                "embeds": [
                    {
                        "title": title,
                        "description": content,
                        "color": color,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                ]
            }

            response = requests.post(self.discord_webhook, json=payload, timeout=10)
            if response.status_code in [200, 204]:
                logger.debug(f"📤 Discord alert sent: {title}")
                self.stats["discord_alerts_sent"] += 1
                return True
            else:
                logger.warning(f"Discord alert failed: {response.status_code}")
                return False

        except Exception as e:
            logger.warning(f"Discord send error: {e}")
            return False

    def _is_trading_hours(self) -> bool:
        """Check if currently in US stock trading hours (9:30 AM - 4:00 PM EST)"""
        now = datetime.now()
        current_time = now.time()

        # Trading hours: 9:30 AM - 4:00 PM EST
        # (Adjust for your timezone if needed)
        start_time = time_type(9, 30)
        end_time = time_type(16, 0)

        # Skip weekends
        if now.weekday() >= 5:
            return False

        return start_time <= current_time <= end_time

    def _should_send_hourly_alert(self) -> bool:
        """Check if we should send hourly sentiment briefing"""
        if not self._is_trading_hours():
            return False

        now = datetime.now()

        # If never sent, send immediately
        if self.last_discord_alert is None:
            return True

        # Check if 1+ hour has passed since last alert
        time_since_last = (now - self.last_discord_alert).total_seconds()
        return time_since_last >= 3600  # 1 hour

    async def send_hourly_sentiment_briefing(self):
        """Send hourly sentiment summary to Discord during trading hours"""
        if not self._should_send_hourly_alert():
            return

        try:
            # Gather current sentiments
            sentiment_data = {}
            for ticker in self.tickers:
                sentiment = self.redis_config.get_sentiment(ticker) if self.redis_config else "unknown"
                sentiment_data[ticker] = sentiment

            # Build alert content
            emoji_map = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}
            lines = []

            for ticker, sentiment in sentiment_data.items():
                emoji = emoji_map.get(sentiment, "❓")
                lines.append(f"{emoji} **{ticker}**: {sentiment.upper()}")

            content = "\n".join(lines)
            content += f"\n\n_Updated: {datetime.now().strftime('%I:%M %p EST')}_"

            # Send to Discord
            self._send_discord_alert(
                title="📊 Trading-Hero Sentiment Briefing (Hourly)",
                content=content,
                color=3447003,  # Blue
            )

            self.last_discord_alert = datetime.now()
            logger.info("✅ Hourly sentiment briefing sent to Discord")

        except Exception as e:
            logger.warning(f"Error sending sentiment briefing: {e}")

    def log_stats(self):
        """Log service statistics"""
        uptime = datetime.now() - self.stats["startup_time"]
        logger.info("\n" + "=" * 80)
        logger.info("SENTIMENT SERVICE STATISTICS")
        logger.info("=" * 80)
        logger.info(f"Uptime: {uptime}")
        logger.info(f"Articles analyzed: {self.stats['articles_analyzed']}")
        logger.info(f"Cache updates: {self.stats['cache_updates']}")
        logger.info(f"Discord alerts sent: {self.stats['discord_alerts_sent']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info("=" * 80 + "\n")


async def main():
    """
    Standalone execution: Start sentiment service.

    Usage:
        python sentiment_worker.py
    """
    # Initialize Redis (required)
    init_redis(host="localhost", port=6379)

    # Create and run service
    service = TradingHeroSentimentService(use_finbert=True)

    # Run continuously
    await service.run_loop(interval_seconds=60)


if __name__ == "__main__":
    asyncio.run(main())
