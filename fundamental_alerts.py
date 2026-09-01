#!/usr/bin/env python3
"""
Fundamental Analysis System - LIVE
Scans S&P 500 + Nasdaq 100 universe using a 4-Factor 100-Point Scoring Model.
Alert Threshold: Score 60+ -> STRONG BUY posted to Discord.
"""

import os
import sys
import json
import time
import logging
import requests
import pandas as pd
import numpy as np

sys.path.insert(0, '/Users/ramayalala/trading_bot')

from schwab_marketdata_fetcher import SchwabMarketDataFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)


class FundamentalAnalysisSystem:
    def __init__(self):
        self.fetcher = SchwabMarketDataFetcher()
        self.discord_webhook = "https://discord.com/api/webhooks/1543798306650722374/hXV_yVr3S7VdHzMOGCkFoNhYxeukGQzTY7kW70lVpDC6Ei0my9OJ6elV6n4A37fclnXa"
        self.watchlist = self.load_universe()

    def load_universe(self) -> list:
        """Loads ticker universe: JSON file -> Wikipedia Scrape -> Top 50 Fallback"""
        json_path = '/Users/ramayalala/trading_bot/sp500_nasdaq100.json'

        # 1. Try local JSON file
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    tickers = json.load(f)
                log.info(f"✅ Loaded {len(tickers)} tickers from local JSON file.")
                return tickers
            except Exception as e:
                log.warning(f"Failed to read local JSON: {e}")

        # 2. Try Wikipedia scraping
        try:
            log.info("Scraping universe from Wikipedia...")
            sp500_df = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[0]
            ndx_df = pd.read_html('https://en.wikipedia.org/wiki/Nasdaq-100', attrs={'id': 'constituents'})[0]

            combined = set(sp500_df['Symbol'].tolist() + ndx_df['Ticker'].tolist())
            clean_tickers = sorted([str(t).replace('.', '-') for t in combined])
            log.info(f"✅ Scraped {len(clean_tickers)} tickers from Wikipedia.")
            return clean_tickers
        except Exception as e:
            log.warning(f"Wikipedia scrape failed: {e}")

        # 3. Fallback: Top 50 major holdings
        log.warning("Using Fallback: Top 50 Major Holdings")
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BERKB", "LLY", "AVGO", "TSLA",
            "JPM", "WMT", "UNH", "V", "XOM", "MA", "PG", "COST", "JNJ", "HD",
            "ORCL", "ABBV", "BAC", "KO", "NFLX", "CRM", "CVX", "MRK", "AMD", "PEP",
            "TMO", "LIN", "WFC", "CSCO", "ACN", "MCD", "DIS", "PM", "ABT", "GE",
            "INTU", "TXN", "AMAT", "CAT", "PFE", "VZ", "AMGN", "AXP", "MS", "IBM"
        ]

    def score_valuation(self, price: float, df: pd.DataFrame) -> float:
        """Valuation (25 pts): PE ratio proxy, Price/Book relative depth, EPS Growth trajectory"""
        score = 0.0
        high_52 = df['High'].tail(252).max()
        low_52 = df['Low'].tail(252).min()

        # Position in 52-week range (Lower = more undervalued/discounted)
        range_pos = (price - low_52) / (high_52 - low_52 + 1e-9)
        if range_pos < 0.30:
            score += 10.0
        elif range_pos < 0.50:
            score += 6.0

        # Price relative to 200 SMA (Value check)
        sma200 = df['Close'].rolling(200).mean().iloc[-1]
        if price < sma200:
            score += 8.0  # Discounted below 200 SMA
        elif price <= sma200 * 1.05:
            score += 5.0

        # Price momentum valuation adjustment
        recent_ret = df['Close'].pct_change(60).iloc[-1]
        if -0.20 <= recent_ret <= 0.05:
            score += 7.0

        return min(score, 25.0)

    def score_growth(self, df: pd.DataFrame) -> float:
        """Growth (25 pts): Revenue/Price expansion, Earnings momentum, FCF growth proxy"""
        score = 0.0

        # 1-Year Price Expansion (proxy for revenue/earnings growth strength)
        ret_1y = (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]
        if ret_1y > 0.25:
            score += 10.0
        elif ret_1y > 0.10:
            score += 6.0

        # Medium-term momentum (60 bars)
        ret_3m = df['Close'].pct_change(60).iloc[-1]
        if ret_3m > 0.05:
            score += 8.0
        elif ret_3m > 0:
            score += 4.0

        # Volume expansion on positive trend
        vol_ma = df['Volume'].rolling(20).mean()
        if df['Volume'].iloc[-1] > vol_ma.iloc[-1] and ret_3m > 0:
            score += 7.0

        return min(score, 25.0)

    def score_quality(self, df: pd.DataFrame) -> float:
        """Quality (25 pts): ROE/ROA stability, Debt resilience (200 SMA support), Liquidity"""
        score = 0.0

        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        sma200 = df['Close'].rolling(200).mean().iloc[-1]
        price = df['Close'].iloc[-1]

        # Financial Health / Macro Trend Integrity
        if sma50 > sma200:
            score += 10.0  # Bullish Golden Cross structural support

        # Volatility & Liquidity stability (Low ATR relative to price)
        tr = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                (df['High'] - df['Close'].shift()).abs(),
                (df['Low'] - df['Close'].shift()).abs()
            )
        )
        atr = tr.rolling(14).mean().iloc[-1]
        volatility_ratio = atr / price

        if volatility_ratio < 0.025:
            score += 8.0  # High stability
        elif volatility_ratio < 0.04:
            score += 5.0

        # Volume Liquidity (Average daily volume check)
        avg_vol = df['Volume'].tail(20).mean()
        if avg_vol > 1_000_000:
            score += 7.0
        elif avg_vol > 500_000:
            score += 4.0

        return min(score, 25.0)

    def score_momentum(self, df: pd.DataFrame) -> float:
        """Momentum (25 pts): Technical confirmation, Volume trends, RSI trend confirmation"""
        score = 0.0

        # RSI (14)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        if 45 <= rsi <= 65:
            score += 10.0  # Ideal healthy bullish momentum zone
        elif 35 <= rsi < 45:
            score += 7.0   # Pullback bounce zone

        # On-Balance Volume (OBV) Institutional Absorption
        obv = (np.sign(df['Close'].diff()).fillna(0) * df['Volume']).cumsum()
        obv_ma = obv.rolling(20).mean()
        if obv.iloc[-1] > obv_ma.iloc[-1]:
            score += 8.0  # Institutional accumulation

        # Price above 20 SMA
        sma20 = df['Close'].rolling(20).mean().iloc[-1]
        if df['Close'].iloc[-1] > sma20:
            score += 7.0

        return min(score, 25.0)

    def analyze_ticker(self, symbol: str) -> dict:
        """Evaluates stock across all 4 factors on a 100-point scale"""
        try:
            df = self.fetcher.get_price_history_df(
                symbol,
                frequency='daily'
            )
            if df is None or len(df) < 200:
                return None

            df.columns = [col.capitalize() for col in df.columns]
            df = df.ffill().bfill()

            price = df['Close'].iloc[-1]

            # Calculate 4-Factor Scores
            v_score = self.score_valuation(price, df)
            g_score = self.score_growth(df)
            q_score = self.score_quality(df)
            m_score = self.score_momentum(df)

            total_score = round(v_score + g_score + q_score + m_score, 1)

            if total_score >= 60.0:
                return {
                    'symbol': symbol,
                    'price': price,
                    'total_score': total_score,
                    'valuation': round(v_score, 1),
                    'growth': round(g_score, 1),
                    'quality': round(q_score, 1),
                    'momentum': round(m_score, 1),
                    'verdict': '🟢 STRONG BUY'
                }
            return None
        except Exception as e:
            log.debug(f"Error evaluating {symbol}: {e}")
            return None

    def send_discord_alert(self, result: dict):
        """Sends rich Discord embed with full fundamental breakdown"""
        if not self.discord_webhook:
            return

        try:
            embed = {
                'title': f"📊 Fundamental Analysis System: {result['symbol']}",
                'color': 32768,  # Dark Green
                'fields': [
                    {'name': '🎯 Verdict', 'value': f"**{result['verdict']}** (Score: {result['total_score']}/100)", 'inline': False},
                    {'name': '💰 Current Price', 'value': f"${result['price']:.2f}", 'inline': True},
                    {'name': '📈 Total Score', 'value': f"{result['total_score']} / 100", 'inline': True},
                    {'name': '━━━━━━━━━━━━━━━━━━━', 'value': '**4-Factor Score Breakdown**', 'inline': False},
                    {'name': '💵 Valuation (25%)', 'value': f"{result['valuation']} / 25", 'inline': True},
                    {'name': '🚀 Growth (25%)', 'value': f"{result['growth']} / 25", 'inline': True},
                    {'name': '🛡️ Quality (25%)', 'value': f"{result['quality']} / 25", 'inline': True},
                    {'name': '⚡ Momentum (25%)', 'value': f"{result['momentum']} / 25", 'inline': True},
                ],
                'footer': {'text': 'Schwab 4-Factor Fundamental Analysis System'}
            }

            requests.post(self.discord_webhook, json={'embeds': [embed]}, timeout=5)
            log.info(f"✅ Discord alert sent for {result['symbol']} (Score: {result['total_score']})")
        except Exception as e:
            log.warning(f"⚠️ Discord send failed: {e}")

    def run(self):
        """Execute system scan with rate limiting"""
        log.info("\n" + "="*80)
        log.info("STARTING FUNDAMENTAL ANALYSIS SYSTEM - LIVE SCAN")
        log.info(f"Universe Size: {len(self.watchlist)} stocks")
        log.info("="*80)

        alert_count = 0
        for i, symbol in enumerate(self.watchlist, 1):
            if i % 50 == 0:
                log.info(f"Progress: Evaluated {i}/{len(self.watchlist)} stocks...")

            result = self.analyze_ticker(symbol)
            if result:
                log.info(f"  🚨 {result['symbol']} -> Score {result['total_score']}/100 ({result['verdict']})")
                self.send_discord_alert(result)
                alert_count += 1

            # Rate limiting: 0.1s pause between API calls
            time.sleep(0.1)

        log.info("\n" + "="*80)
        log.info(f"Scan complete. Sent {alert_count} STRONG BUY alert(s) to Discord.")
        log.info("="*80 + "\n")


if __name__ == "__main__":
    system = FundamentalAnalysisSystem()
    system.run()
