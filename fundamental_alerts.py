#!/usr/bin/env python3
"""
Fundamental Analysis System - LIVE (Refined Pullback & Accumulation Engine)
Scans stock universe using a 4-Factor 100-Point Scoring Model.
Alert Threshold: Score 55+ -> STRONG BUY posted to Discord.
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
        json_path = '/Users/ramayalala/trading_bot/sp500_nasdaq100.json'

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    tickers = json.load(f)
                log.info(f"✅ Loaded {len(tickers)} tickers from local JSON file.")
                return [t.replace('.', '-') for t in tickers]
            except Exception as e:
                log.warning(f"Failed to read local JSON: {e}")

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

        # Fixed BRK-B ticker mapping for Schwab compatibility
        return [
            "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "LLY", "AVGO", "TSLA",
            "JPM", "WMT", "UNH", "V", "XOM", "MA", "PG", "COST", "JNJ", "HD",
            "ORCL", "ABBV", "BAC", "KO", "NFLX", "CRM", "CVX", "MRK", "AMD", "PEP",
            "TMO", "LIN", "WFC", "CSCO", "ACN", "MCD", "DIS", "PM", "ABT", "GE",
            "INTU", "TXN", "AMAT", "CAT", "PFE", "VZ", "AMGN", "AXP", "MS", "IBM"
        ]

    def score_valuation(self, price: float, df: pd.DataFrame) -> float:
        """Valuation (25 pts): Rewards pullback discount relative to recent highs & key SMAs"""
        score = 0.0
        high_52 = df['High'].tail(252).max()
        low_52 = df['Low'].tail(252).min()
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        sma200 = df['Close'].rolling(200).mean().iloc[-1]

        # 1. Healthy Pullback Depth (5% to 18% off 52-week high)
        pct_off_high = (high_52 - price) / high_52
        if 0.05 <= pct_off_high <= 0.18:
            score += 10.0
        elif 0.02 <= pct_off_high < 0.05:
            score += 6.0

        # 2. Key SMA Retest (Near 20-day, 50-day, or 200-day dynamic support)
        sma20 = df['Close'].rolling(20).mean().iloc[-1]
        dist_sma20 = abs(price - sma20) / sma20
        dist_sma50 = abs(price - sma50) / sma50

        if dist_sma20 <= 0.02 or dist_sma50 <= 0.025:
            score += 8.0  # Retesting dynamic support zone
        elif price > sma200:
            score += 4.0

        # 3. Macro Structural Discount (Price within 5% of 200 SMA)
        if 0.95 * sma200 <= price <= 1.05 * sma200:
            score += 7.0

        return min(score, 25.0)

    def score_growth(self, df: pd.DataFrame) -> float:
        """Growth (25 pts): Verifies underlying multi-month bull regime"""
        score = 0.0

        # 1. 1-Year Price Trend Integrity
        ret_1y = (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]
        if ret_1y > 0.20:
            score += 10.0
        elif ret_1y > 0.08:
            score += 6.0

        # 2. 6-Month Momentum Trend
        ret_6m = df['Close'].pct_change(126).iloc[-1]
        if ret_6m > 0.10:
            score += 8.0
        elif ret_6m > 0.03:
            score += 4.0

        # 3. Volume Drying Up on Pullback (Low volume dip = no institutional selling)
        vol_20ma = df['Volume'].rolling(20).mean().iloc[-1]
        curr_vol = df['Volume'].iloc[-1]
        ret_5d = df['Close'].pct_change(5).iloc[-1]

        if ret_5d < 0 and curr_vol < vol_20ma:
            score += 7.0  # Healthy low-volume retracement

        return min(score, 25.0)

    def score_quality(self, df: pd.DataFrame) -> float:
        """Quality (25 pts): Golden cross alignment, low volatility, high liquidity"""
        score = 0.0
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        sma200 = df['Close'].rolling(200).mean().iloc[-1]
        price = df['Close'].iloc[-1]

        # 1. Macro Bullish Structure (50 SMA > 200 SMA)
        if sma50 > sma200:
            score += 10.0

        # 2. Volatility Compression Check (ATR Ratio)
        tr = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                (df['High'] - df['Close'].shift()).abs(),
                (df['Low'] - df['Close'].shift()).abs()
            )
        )
        atr = tr.rolling(14).mean().iloc[-1]
        if (atr / price) < 0.03:
            score += 8.0
        elif (atr / price) < 0.045:
            score += 5.0

        # 3. Liquidity Floor
        avg_vol = df['Volume'].tail(20).mean()
        if avg_vol > 1_000_000:
            score += 7.0
        elif avg_vol > 400_000:
            score += 4.0

        return min(score, 25.0)

    def score_momentum(self, df: pd.DataFrame) -> float:
        """Momentum (25 pts): Oversold RSI bounce + OBV Institutional Accumulation"""
        score = 0.0

        # 1. RSI (14) Pullback / Oversold Rebound Zone
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi = (100 - (100 / (1 + rs))).iloc[-1]

        if 40 <= rsi <= 55:
            score += 10.0  # Perfect swing pullback zone
        elif 30 <= rsi < 40:
            score += 8.0   # Deep oversold bounce setup

        # 2. OBV Accumulation (Rising OBV while price pulls back = Hidden Buying)
        obv = (np.sign(df['Close'].diff()).fillna(0) * df['Volume']).cumsum()
        obv_sma20 = obv.rolling(20).mean().iloc[-1]
        if obv.iloc[-1] > obv_sma20:
            score += 8.0

        # 3. Dynamic Support Hold (Price above 50 SMA)
        sma50 = df['Close'].rolling(50).mean().iloc[-1]
        if df['Close'].iloc[-1] >= sma50:
            score += 7.0

        return min(score, 25.0)

    def analyze_ticker(self, symbol: str) -> dict:
        try:
            df = self.fetcher.get_price_history_df(symbol, frequency='daily')
            if df is None or len(df) < 200:
                return None

            df.columns = [col.capitalize() for col in df.columns]
            df = df.ffill().bfill()
            price = df['Close'].iloc[-1]

            v_score = self.score_valuation(price, df)
            g_score = self.score_growth(df)
            q_score = self.score_quality(df)
            m_score = self.score_momentum(df)

            total_score = round(v_score + g_score + q_score + m_score, 1)

            # Lowered threshold to 55.0 to capture top-tier pullback opportunities
            if total_score >= 55.0:
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
        if not self.discord_webhook:
            return

        try:
            embed = {
                'title': f"📊 Fundamental Analysis System: {result['symbol']}",
                'color': 32768,
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
                'footer': {'text': 'Schwab 4-Factor Fundamental Analysis System - Institutional Accumulation Engine'}
            }
            requests.post(self.discord_webhook, json={'embeds': [embed]}, timeout=5)
            log.info(f"✅ Discord alert sent for {result['symbol']} (Score: {result['total_score']})")
        except Exception as e:
            log.warning(f"⚠️ Discord send failed: {e}")

    def run(self):
        log.info("\n" + "="*80)
        log.info("STARTING FUNDAMENTAL ANALYSIS SYSTEM - LIVE SCAN")
        log.info(f"Universe Size: {len(self.watchlist)} stocks | Threshold: 55+/100")
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

            time.sleep(0.1)

        log.info("\n" + "="*80)
        log.info(f"Scan complete. Sent {alert_count} STRONG BUY alert(s) to Discord.")
        log.info("="*80 + "\n")


if __name__ == "__main__":
    system = FundamentalAnalysisSystem()
    system.run()
