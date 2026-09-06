"""
Phase 3B: Redis Configuration for Sentiment Cache

Template for async sentiment service integration.
When enabled, sentiment_worker.py maintains ticker-level sentiment in Redis.
Main bot queries cache with zero-latency lookups.

Toggle: SENTIMENT_ENABLED in uw_config.py
"""

import redis
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RedisConfig:
    """Redis connection + cache management"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        sentiment_ttl: int = 900,  # 15 minutes
    ):
        self.host = host
        self.port = port
        self.db = db
        self.sentiment_ttl = sentiment_ttl
        self.client: Optional[redis.Redis] = None

    def connect(self) -> bool:
        """Establish Redis connection"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            # Test connection
            self.client.ping()
            logger.info(f"✅ Redis connected: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {e}")
            logger.warning("📌 Sentiment service disabled (Redis unavailable)")
            self.client = None
            return False

    def get_sentiment(self, ticker: str) -> str:
        """Fetch pre-computed sentiment from cache (microsecond latency)"""
        if self.client is None:
            return "neutral"

        try:
            sentiment = self.client.get(f"SENTIMENT:{ticker}")
            return sentiment if sentiment else "neutral"
        except Exception as e:
            logger.warning(f"Redis read error for {ticker}: {e}")
            return "neutral"

    def set_sentiment(self, ticker: str, sentiment: str, ttl: Optional[int] = None) -> bool:
        """Cache sentiment with TTL"""
        if self.client is None:
            return False

        try:
            ttl = ttl or self.sentiment_ttl
            self.client.setex(
                name=f"SENTIMENT:{ticker}", time=ttl, value=sentiment
            )
            logger.debug(f"📌 Cached {ticker} sentiment: {sentiment} (TTL={ttl}s)")
            return True
        except Exception as e:
            logger.warning(f"Redis write error for {ticker}: {e}")
            return False

    def clear_all_sentiments(self):
        """Clear all cached sentiments"""
        if self.client is None:
            return

        try:
            pattern = "SENTIMENT:*"
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
                logger.info(f"🗑️ Cleared {len(keys)} sentiment entries from Redis")
        except Exception as e:
            logger.warning(f"Redis clear error: {e}")

    def health_check(self) -> bool:
        """Check if Redis is still responsive"""
        if self.client is None:
            return False

        try:
            self.client.ping()
            return True
        except Exception:
            return False


# Global instance
_redis_config: Optional[RedisConfig] = None


def get_redis_config() -> RedisConfig:
    """Lazy initialization of Redis config"""
    global _redis_config
    if _redis_config is None:
        _redis_config = RedisConfig()
    return _redis_config


def init_redis(host: str = "localhost", port: int = 6379) -> bool:
    """Initialize Redis connection"""
    global _redis_config
    _redis_config = RedisConfig(host=host, port=port)
    return _redis_config.connect()
