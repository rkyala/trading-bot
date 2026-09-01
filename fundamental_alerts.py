#!/usr/bin/env python3
"""
Fundamental Analysis Alerts - S&P 500 + Nasdaq 100
Screens entire indices based on earnings, valuation, growth, quality
Generates daily Discord alerts on best opportunities
"""

import sys
import logging
import os
import time
from datetime import datetime
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

class FundamentalAlerter:
    def __init__(self):
        self.fetcher = SchwabMarketDataFetcher()
        self.discord_webhook = "https://discord.com/api/webhooks/1543798306650722374/hXV_yVr3S7VdHzMOGCkFoNhYxeukGQzTY7kW70lVpDC6Ei0my9OJ6elV6n4A37fclnXa"

        # Dynamically fetch ~550 tickers from S&P 500 + Nasdaq 100
        self.watchlist = self.fetch_index_tickers()

    def fetch_index_tickers(self):
        """Dynamically fetch current S&P 500 and Nasdaq 100 tickers from Wikipedia"""
        log.info("Fetching S&P 500 and Nasdaq 100 constituents from Wikipedia...")
        try:
            # Set User-Agent to avoid 403 Forbidden
            headers = {'User-Agent': 'Mozilla/5.0 (Trading Bot)'}

            # S&P 500
            sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            sp500_df = pd.read_html(sp500_url, header=0)[0]
            sp500_tickers = sp500_df['Symbol'].tolist()
            log.info(f"  • S&P 500: {len(sp500_tickers)} tickers")

            # Nasdaq 100
            ndx_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            ndx_df = pd.read_html(ndx_url, attrs={'id': 'constituents'})[0]
            ndx_tickers = ndx_df['Ticker'].tolist()
            log.info(f"  • Nasdaq 100: {len(ndx_tickers)} tickers")

            # Combine, deduplicate, and clean (replace dots with hyphens for API compatibility)
            combined = set(sp500_tickers + ndx_tickers)
            clean_tickers = sorted([str(t).replace('.', '-') for t in combined])

            log.info(f"✅ Successfully loaded {len(clean_tickers)} unique tickers")
            return clean_tickers

        except Exception as e:
            log.error(f"Failed to fetch index lists: {e}")
            # Fallback to comprehensive list of major holdings
            log.warning("Using fallback ticker list (top 50 stocks)...")
            fallback = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BERKB',
                'JPMORGCHASE', 'WMT', 'XOM', 'UNH', 'MA', 'V', 'PG', 'KO', 'JNJ',
                'WFC', 'BAC', 'C', 'GM', 'F', 'IBM', 'INTC', 'AMD', 'QCOM', 'CSCO',
                'ORCL', 'CRM', 'ADBE', 'NFLX', 'PYPL', 'SQ', 'SHOP', 'ROKU', 'ABNB',
                'UBER', 'LYFT', 'DASH', 'MSTR', 'MU', 'LRCX', 'ASML', 'AVGO', 'NXPI',
                'INTU', 'SNPS', 'CDNS', 'ADSK', 'ANET', 'TEAM'
            ]
            return sorted(fallback)

    def fetch_fundamentals(self, symbol):
        """Fetch fundamental data from Schwab"""
        try:
            # Get quotes first
            quotes = self.fetcher.get_equity_quotes([symbol])
            if not quotes or symbol not in quotes:
                return None

            quote = quotes[symbol]
            price = quote.get('lastPrice', 0)

            # Get fundamentals
            try:
                fundamentals = self.fetcher.get_equity_fundamentals(symbol)
                if not fundamentals:
                    return None
            except Exception as e:
                log.warning(f"⚠️ {symbol}: Fundamentals unavailable - {e}")
                return None

            return {
                'symbol': symbol,
                'price': price,
                'quote': quote,
                'fundamentals': fundamentals
            }

        except Exception as e:
            log.warning(f"⚠️ {symbol}: {e}")
            return None

    def analyze_fundamentals(self, data):
        """Score stocks based on fundamental metrics"""
        if not data or not data.get('fundamentals'):
            return None

        symbol = data['symbol']
        price = data['price']
        fund = data['fundamentals']
        quote = data['quote']

        # Extract key metrics
        scores = {
            'valuation': 0,
            'growth': 0,
            'quality': 0,
            'momentum': 0
        }

        alerts = []

        # 1. VALUATION METRICS
        try:
            pe_ratio = fund.get('peRatio', None)
            pb_ratio = fund.get('priceBookRatio', None)
            eps = fund.get('eps', None)
            eps_ttm = fund.get('epsTTM', None)

            # Low PE = undervalued
            if pe_ratio and 0 < pe_ratio < 15:
                scores['valuation'] += 40
                alerts.append({
                    'type': '💰 UNDERVALUED',
                    'metric': f'PE {pe_ratio:.1f}x (Low)',
                    'strength': 'HIGH'
                })
            elif pe_ratio and 15 <= pe_ratio <= 25:
                scores['valuation'] += 20

            # Low PB = value play
            if pb_ratio and pb_ratio < 1.0:
                scores['valuation'] += 30
                alerts.append({
                    'type': '📊 VALUE PLAY',
                    'metric': f'Price/Book {pb_ratio:.2f} (<1.0)',
                    'strength': 'HIGH'
                })

            # Strong EPS growth
            if eps_ttm and eps_ttm > 0 and eps and eps > eps_ttm * 0.5:
                scores['growth'] += 30
                growth_pct = ((eps - eps_ttm) / eps_ttm * 100) if eps_ttm > 0 else 0
                alerts.append({
                    'type': '📈 EARNINGS GROWTH',
                    'metric': f'EPS growth {growth_pct:.1f}%',
                    'strength': 'HIGH'
                })

        except Exception as e:
            log.debug(f"Valuation calc failed: {e}")

        # 2. GROWTH METRICS
        try:
            revenue_growth = fund.get('revenueGrowth', None)
            earnings_growth = fund.get('earningsGrowth', None)
            fcf_growth = fund.get('fcfGrowth', None)

            if revenue_growth and revenue_growth > 0.15:  # >15% growth
                scores['growth'] += 25
                alerts.append({
                    'type': '🚀 HIGH GROWTH',
                    'metric': f'Revenue +{revenue_growth*100:.1f}%',
                    'strength': 'MEDIUM'
                })

            if earnings_growth and earnings_growth > 0.20:  # >20% growth
                scores['growth'] += 30
                alerts.append({
                    'type': '📊 EARNINGS MOMENTUM',
                    'metric': f'Earnings +{earnings_growth*100:.1f}%',
                    'strength': 'HIGH'
                })

        except Exception as e:
            log.debug(f"Growth calc failed: {e}")

        # 3. QUALITY METRICS
        try:
            roe = fund.get('returnOnEquity', None)
            roa = fund.get('returnOnAssets', None)
            debt_ratio = fund.get('debtToEquity', None)
            current_ratio = fund.get('currentRatio', None)

            # High ROE = quality
            if roe and roe > 0.15:  # >15% ROE
                scores['quality'] += 35
                alerts.append({
                    'type': '⭐ HIGH QUALITY',
                    'metric': f'ROE {roe*100:.1f}% (Strong)',
                    'strength': 'HIGH'
                })

            # Low debt = safe
            if debt_ratio and debt_ratio < 0.5:
                scores['quality'] += 25
                alerts.append({
                    'type': '🛡️ LOW DEBT',
                    'metric': f'Debt/Equity {debt_ratio:.2f}',
                    'strength': 'MEDIUM'
                })

            # Strong liquidity
            if current_ratio and current_ratio > 2.0:
                scores['quality'] += 20
                alerts.append({
                    'type': '💧 STRONG LIQUIDITY',
                    'metric': f'Current Ratio {current_ratio:.2f}',
                    'strength': 'MEDIUM'
                })

        except Exception as e:
            log.debug(f"Quality calc failed: {e}")

        # 4. MOMENTUM (from quote)
        try:
            change_pct = quote.get('netPercentChange', 0)
            if change_pct > 5:
                scores['momentum'] += 25
                alerts.append({
                    'type': '📈 MOMENTUM',
                    'metric': f'Up {change_pct:.1f}%',
                    'strength': 'MEDIUM'
                })
        except Exception as e:
            log.debug(f"Momentum calc failed: {e}")

        # Overall score
        total_score = sum(scores.values()) / 4
        scores['total'] = total_score

        return {
            'symbol': symbol,
            'price': price,
            'scores': scores,
            'alerts': alerts,
            'fundamentals': fund
        }

    def generate_summary(self, analysis):
        """Create trading summary from analysis"""
        if not analysis or not analysis['alerts']:
            return None

        symbol = analysis['symbol']
        alerts = analysis['alerts']
        scores = analysis['scores']

        # Determine verdict
        total_score = scores['total']
        if total_score >= 70:
            verdict = "🟢 STRONG BUY - Excellent fundamentals"
            confidence = "HIGH"
        elif total_score >= 50:
            verdict = "🟡 BUY - Good opportunity"
            confidence = "MEDIUM"
        elif total_score >= 30:
            verdict = "⚪ HOLD - Neutral setup"
            confidence = "LOW"
        else:
            verdict = "🔴 AVOID - Weak fundamentals"
            confidence = "CAUTION"

        return {
            'symbol': symbol,
            'price': analysis['price'],
            'verdict': verdict,
            'confidence': confidence,
            'score': f"{total_score:.0f}/100",
            'valuation_score': f"{scores['valuation']:.0f}/100",
            'growth_score': f"{scores['growth']:.0f}/100",
            'quality_score': f"{scores['quality']:.0f}/100",
            'alerts': alerts,
            'fund': analysis['fundamentals']
        }

    def send_alert(self, summary):
        """Send to Discord"""
        if not summary or not self.discord_webhook:
            return False

        try:
            symbol = summary['symbol']
            price = summary['price']
            verdict = summary['verdict']

            # Color by verdict
            if 'STRONG BUY' in verdict:
                color = 32768  # Dark green
            elif 'BUY' in verdict:
                color = 65280  # Bright green
            elif 'HOLD' in verdict:
                color = 16776960  # Yellow
            else:
                color = 16711680  # Red

            # Build alert list
            alert_text = '\n'.join([f"{a['type']}: {a['metric']}" for a in summary['alerts']])

            embed = {
                'title': f"{symbol} - ${price:.2f}",
                'color': color,
                'fields': [
                    {'name': '📋 Verdict', 'value': verdict, 'inline': False},
                    {'name': '🎯 Confidence', 'value': summary['confidence'], 'inline': True},
                    {'name': '📊 Score', 'value': summary['score'], 'inline': True},
                    {'name': '💰 Valuation', 'value': summary['valuation_score'], 'inline': True},
                    {'name': '📈 Growth', 'value': summary['growth_score'], 'inline': True},
                    {'name': '⭐ Quality', 'value': summary['quality_score'], 'inline': True},
                    {'name': '🔍 Key Signals', 'value': alert_text, 'inline': False},
                ]
            }

            payload = {
                'embeds': [embed],
                'username': '💼 Fundamental Analysis'
            }

            response = requests.post(self.discord_webhook, json=payload, timeout=5)
            return response.status_code == 204

        except Exception as e:
            log.warning(f"Discord send failed: {e}")
            return False

    def run(self):
        """Scan all symbols"""
        log.info("\n" + "="*80)
        log.info("FUNDAMENTAL ANALYSIS - S&P 500 + Nasdaq 100")
        log.info("="*80)

        results = []
        top_opportunities = []

        for i, symbol in enumerate(self.watchlist, 1):
            # Progress update every 50 stocks
            if i % 50 == 0:
                log.info(f"Progress: {i}/{len(self.watchlist)} stocks scanned...")

            # Fetch fundamentals
            data = self.fetch_fundamentals(symbol)
            if not data:
                time.sleep(0.1)  # Rate limit
                continue

            # Analyze
            analysis = self.analyze_fundamentals(data)
            if not analysis:
                time.sleep(0.1)  # Rate limit
                continue

            # Generate summary
            summary = self.generate_summary(analysis)
            if not summary:
                time.sleep(0.1)  # Rate limit
                continue

            results.append(summary)

            # Track top opportunities
            score = analysis['scores']['total']
            if score >= 50:  # Only track good opportunities
                top_opportunities.append((symbol, score, summary))

            # Send individual alert if score >= 60
            if score >= 60:
                if self.send_alert(summary):
                    log.info(f"   ✅ {symbol}: Alert sent - {summary['verdict']}")

            # Rate limiting - brief pause between API calls
            time.sleep(0.1)

        # Summary report
        log.info("\n" + "="*80)
        log.info("TOP OPPORTUNITIES")
        log.info("="*80)

        # Sort by score
        top_opportunities.sort(key=lambda x: x[1], reverse=True)

        for i, (symbol, score, summary) in enumerate(top_opportunities[:10], 1):
            log.info(f"{i}. {symbol} ({score:.0f}/100) - {summary['verdict']}")

        log.info("\n" + "="*80)
        log.info(f"Scan complete: {len(results)} stocks analyzed, {len([r for r in results if r['confidence'] in ['HIGH', 'MEDIUM']])} opportunities")
        log.info("="*80 + "\n")

        return results, top_opportunities

if __name__ == "__main__":
    alerter = FundamentalAlerter()
    results, opportunities = alerter.run()
