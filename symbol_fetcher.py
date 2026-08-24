#!/usr/bin/env python3
"""
Dynamic Symbol Fetcher - Top 50 Trending from yfinance
Fetches trending stocks by volume, momentum, and volatility
Includes market cap filtering for liquid, established equities
"""

import logging
import pandas as pd
import yfinance as yf
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import concurrent.futures

logger = logging.getLogger(__name__)


# ============================================================================
# MARKET CAP FILTER
# ============================================================================

class MarketCapFilter:
    """Filters out micro/small-caps and illiquid stocks before strategy screening"""

    @staticmethod
    def filter_tickers(symbols: List[str],
                      min_market_cap: float = 10_000_000_000,
                      min_avg_volume: int = 1_000_000) -> List[str]:
        """
        Filter symbols by minimum market cap and average volume

        Args:
            symbols: List of ticker symbols to filter
            min_market_cap: Minimum market cap in dollars (default $10B)
            min_avg_volume: Minimum 3-month average volume (default 1M shares)

        Returns:
            Filtered list of symbols meeting criteria
        """
        logger.info("=" * 80)
        logger.info(f"FILTERING BY MARKET CAP (min: ${min_market_cap/1e9:.1f}B, vol: {min_avg_volume/1e6:.1f}M)")
        logger.info("=" * 80)

        filtered_symbols = []
        skipped = 0

        for i, symbol in enumerate(symbols, 1):
            try:
                ticker = yf.Ticker(symbol)
                fast_info = ticker.fast_info

                # Get market cap and volume
                market_cap = fast_info.get("marketCap") or 0
                avg_volume = fast_info.get("threeMonthAverageVolume") or 0
                price = fast_info.get("currentPrice") or 0

                # Check criteria
                if market_cap >= min_market_cap and avg_volume >= min_avg_volume:
                    filtered_symbols.append(symbol)
                    logger.info(
                        f"✅ [{i:3}/{len(symbols)}] {symbol:6} | "
                        f"Cap: ${market_cap/1e9:6.2f}B | "
                        f"Vol: {avg_volume/1e6:6.1f}M | "
                        f"Price: ${price:8.2f}"
                    )
                else:
                    skipped += 1
                    cap_str = f"${market_cap/1e9:.2f}B" if market_cap else "N/A"
                    vol_str = f"{avg_volume/1e6:.1f}M" if avg_volume else "N/A"
                    logger.debug(
                        f"🚫 [{i:3}/{len(symbols)}] {symbol:6} | "
                        f"Cap: {cap_str:>8} (req ${min_market_cap/1e9:.1f}B) | "
                        f"Vol: {vol_str:>8} (req {min_avg_volume/1e6:.1f}M)"
                    )

            except Exception as e:
                logger.debug(f"⚠️  [{i:3}/{len(symbols)}] {symbol:6} | Error: {e}")
                skipped += 1
                continue

        logger.info("=" * 80)
        logger.info(f"✅ FILTERED: {len(symbols)} → {len(filtered_symbols)} symbols")
        logger.info(f"   Passed: {len(filtered_symbols)} | Skipped: {skipped}")
        logger.info("=" * 80)

        return filtered_symbols


class DynamicSymbolFetcher:
    """Fetch top 50 trending symbols from yfinance"""

    # Popular stocks to scan for trending behavior
    POPULAR_STOCKS = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK-B', 'JNJ', 'V',
        'WMT', 'JPM', 'PG', 'XOM', 'CVX', 'KO', 'LLY', 'ABT', 'MCD', 'BA',
        'NFLX', 'ADBE', 'CRM', 'IBM', 'INTC', 'AMD', 'QCOM', 'CSCO', 'VZ', 'T',
        'AXP', 'MU', 'PYPL', 'BKNG', 'SBUX', 'CMG', 'COIN', 'INTU', 'SQ', 'SHOP',
        'ABNB', 'DDOG', 'ZM', 'CRWD', 'OKTA', 'NET', 'FSLY', 'SNOW', 'DASH', 'UBER',
        'LYFT', 'GrubHub', 'PINS', 'SNAP', 'RBLX', 'U', 'PLTR', 'F', 'GM', 'LCID',
        'RIVN', 'NIO', 'XPEV', 'CPNG', 'PDD', 'BABA', 'JD', 'BILI', 'ASHR', 'EWZ',
        'GLD', 'TLT', 'USO', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU',
        'XLV', 'XLY', 'DIA', 'QQQ', 'SPY', 'IWM', 'EEM', 'FXI', 'EWH', 'EWG',
        'EWJ', 'EWU', 'EWW', 'RSX', 'ARKG', 'ARKK', 'ARKW', 'ARKF', 'ARKS', 'PSP'
    ]

    @staticmethod
    def calculate_trend_score(symbol: str) -> Optional[Dict]:
        """
        Calculate trend score for a symbol using:
        - Volume (higher = more liquid)
        - Momentum (% change over last 5 days)
        - Volatility (std dev)
        """
        try:
            # Get 5-day data with 1-hour intervals
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d", interval="1h")

            if hist.empty or len(hist) < 20:
                return None

            close = hist['Close'].astype(float)
            volume = hist['Volume'].astype(float)

            # Calculate metrics
            total_volume = volume.sum()
            avg_volume = volume.mean()

            # Momentum: 5-day return
            momentum = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100

            # Volatility: standard deviation of returns
            returns = close.pct_change().dropna()
            volatility = returns.std() * 100

            # Volatility-adjusted momentum (trending with volatility = opportunity)
            trend_score = abs(momentum) * volatility * (total_volume / 1_000_000)

            return {
                'symbol': symbol,
                'score': trend_score,
                'volume_millions': total_volume / 1_000_000,
                'momentum_pct': momentum,
                'volatility_pct': volatility,
                'last_price': close.iloc[-1]
            }
        except Exception as e:
            logger.debug(f"Error analyzing {symbol}: {e}")
            return None

    @staticmethod
    def get_top_trending(max_symbols: int = 50) -> List[str]:
        """
        Fetch top 50 trending symbols by analyzing popular stocks
        Uses parallel processing to speed up yfinance downloads
        """
        logger.info(f"[*] Fetching top {max_symbols} trending symbols from yfinance...")
        logger.info(f"    Analyzing {len(DynamicSymbolFetcher.POPULAR_STOCKS)} popular stocks...")

        trending_data = []

        # Use ThreadPoolExecutor for parallel yfinance downloads
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(DynamicSymbolFetcher.calculate_trend_score, symbol): symbol
                for symbol in DynamicSymbolFetcher.POPULAR_STOCKS
            }

            completed = 0
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                symbol = futures[future]

                try:
                    result = future.result()
                    if result:
                        trending_data.append(result)
                except Exception as e:
                    logger.debug(f"Error processing {symbol}: {e}")

                # Progress indicator
                if completed % 10 == 0:
                    logger.info(f"    Progress: {completed}/{len(DynamicSymbolFetcher.POPULAR_STOCKS)}")

        if not trending_data:
            logger.warning("No trending symbols found, using fallback")
            return DynamicSymbolFetcher.POPULAR_STOCKS[:max_symbols]

        # Sort by trend score (descending)
        trending_data.sort(key=lambda x: x['score'], reverse=True)

        # Get top N and extract symbols
        top_symbols = [t['symbol'] for t in trending_data[:max_symbols]]

        # Log results
        logger.info(f"✅ Found {len(top_symbols)} trending symbols from yfinance")
        logger.info(f"\n📊 TOP {min(20, len(top_symbols))} TRENDING:")
        for i, trend in enumerate(trending_data[:20], 1):
            symbol = trend['symbol']
            score = trend['score']
            momentum = trend['momentum_pct']
            volume = trend['volume_millions']
            volatility = trend['volatility_pct']
            price = trend['last_price']

            logger.info(
                f"   {i:2}. {symbol:6} | Score: {score:10.2f} | "
                f"Momentum: {momentum:+7.2f}% | Vol: {volume:6.1f}M | "
                f"Volatility: {volatility:5.1f}% | Price: ${price:8.2f}"
            )

        if len(top_symbols) > 20:
            logger.info(f"   ... and {len(top_symbols) - 20} more")

        return top_symbols

    @staticmethod
    def get_trending_symbols(config: Dict) -> List[str]:
        """
        Main method: Fetch trending symbols based on config
        Applies market cap filter for liquid equities
        """
        dynamic_cfg = config.get("strategy", {}).get("dynamic_symbols", {})

        if not dynamic_cfg.get("enabled"):
            logger.info("Dynamic symbols disabled")
            return []

        max_symbols = dynamic_cfg.get("max_symbols", 50)
        min_market_cap = dynamic_cfg.get("min_market_cap", 10_000_000_000)  # $10B default
        min_avg_volume = dynamic_cfg.get("min_avg_volume", 1_000_000)  # 1M default

        logger.info("=" * 80)
        logger.info("FETCHING TOP TRENDING SYMBOLS FROM YFINANCE")
        logger.info("=" * 80)

        # Step 1: Get top trending
        trending_symbols = DynamicSymbolFetcher.get_top_trending(max_symbols * 2)  # Get 2x to account for filtering

        # Step 2: Apply market cap filter
        filtered_symbols = MarketCapFilter.filter_tickers(
            trending_symbols,
            min_market_cap=min_market_cap,
            min_avg_volume=min_avg_volume
        )

        # Step 3: Return top N after filtering
        final_symbols = filtered_symbols[:max_symbols]

        logger.info(f"✅ Ready to scan {len(final_symbols)} liquid, established equities\n")

        return final_symbols
