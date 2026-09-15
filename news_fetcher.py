#!/usr/bin/env python3
"""
News Fetcher: Real-time news headlines for trading symbols

Fetches latest news from free RSS feeds (no API key required)
- Bloomberg, CNBC, Yahoo Finance
- ~5 second latency
- Zero cost
"""

import logging
import feedparser
import requests
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


class NewsFetcher:
    """Fetch latest news for stock symbols"""

    def __init__(self):
        """Initialize news fetcher"""
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes

    def get_latest_news(self, symbol, max_articles=5):
        """
        Fetch latest news for a symbol

        Args:
            symbol: Stock ticker (e.g., "INTC")
            max_articles: Max headlines to return

        Returns:
            List of articles: [{"title": "...", "summary": "...", "source": "..."}]
        """

        # Check cache
        if symbol in self.cache:
            cache_time, articles = self.cache[symbol]
            if (datetime.now() - cache_time).total_seconds() < self.cache_ttl:
                log.debug(f"Using cached news for {symbol}")
                return articles

        articles = []

        # Try multiple free RSS feeds
        feeds = [
            {
                "name": "Yahoo Finance",
                "url": f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}",
            },
            {
                "name": "MarketWatch",
                "url": "https://feeds.marketwatch.com/marketwatch/topstories/",
            },
            {"name": "Seeking Alpha", "url": "https://seekingalpha.com/feed.xml"},
        ]

        for feed_info in feeds:
            try:
                parsed = feedparser.parse(feed_info["url"])

                for entry in parsed.entries[:max_articles]:
                    # Filter for symbol in title or summary
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")

                    if symbol.lower() in title.lower() or symbol.lower() in summary.lower():
                        articles.append(
                            {
                                "title": title[:100],
                                "summary": summary[:200],
                                "source": feed_info["name"],
                                "published": entry.get("published", ""),
                            }
                        )

                if articles:
                    break  # Stop if we found articles

            except Exception as e:
                log.debug(f"Error fetching from {feed_info['name']}: {e}")
                continue

        # Cache results
        self.cache[symbol] = (datetime.now(), articles)

        if articles:
            log.info(f"✅ Found {len(articles)} news items for {symbol}")
        else:
            log.debug(f"No recent news for {symbol}")

        return articles


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = NewsFetcher()

    symbols = ["INTC", "AMD", "NVDA"]
    for symbol in symbols:
        news = fetcher.get_latest_news(symbol, max_articles=3)
        print(f"\n{symbol}:")
        for article in news:
            print(f"  • {article['title']}")
