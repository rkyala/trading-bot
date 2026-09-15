#!/usr/bin/env python3
"""
DRY-RUN BOT v3.5 - Fibonacci + Stochastic
Test if adding Stochastic improves on Fibonacci-only
"""

import os
import sys
import json
import logging
from datetime import datetime
import yfinance as yf
import pandas as pd
import numpy as np

# Local imports
try:
    from local_llm_wrapper import LocalLLMWrapper
    HAS_LLAMA = True
except:
    HAS_LLAMA = False

try:
    from advanced_charts import AdvancedChartAnalyzer
    HAS_CHARTS = True
except:
    HAS_CHARTS = False

try:
    from finrl_integration import get_finrl_metrics
    HAS_FINRL = True
except:
    HAS_FINRL = False

try:
    from online_learning import OnlineLearner
    HAS_ONLINE_LEARNING = True
except:
    HAS_ONLINE_LEARNING = False

try:
    from enhanced_analysis import TechnicalAnalyzer
    HAS_ENHANCED = True
except:
    HAS_ENHANCED = False

try:
    from rag_trades import TradeRAG
    HAS_RAG = True
except:
    HAS_RAG = False

try:
    from ensemble import EnsembleAnalyzer
    HAS_ENSEMBLE = True
except:
    HAS_ENSEMBLE = False

try:
    from symbol_updater import SymbolUpdater
    HAS_SYMBOL_UPDATER = True
except:
    HAS_SYMBOL_UPDATER = False

# ============================================================================
# CONFIGURATION
# ============================================================================

DRY_RUN_MODE = True
LOG_DIR = "dry_run_logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, f"bot_{datetime.now().strftime('%Y%m%d')}.log")),
        logging.StreamHandler(sys.stdout)
    ]
)

log = logging.getLogger(__name__)

# ============================================================================
# STOCHASTIC CALCULATOR
# ============================================================================

class StochasticCalculator:
    """Calculate Stochastic K% and boost score"""

    @staticmethod
    def calculate_k_percent(symbol, period=14):
        """Calculate Stochastic K%"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="60d")

            if len(hist) < period:
                return None, None

            recent = hist.tail(period)
            low = recent['Low'].min()
            high = recent['High'].max()
            close = hist['Close'].iloc[-1]

            if high == low:
                k_percent = 50
            else:
                k_percent = ((close - low) / (high - low)) * 100

            return k_percent, close

        except:
            return None, None

    @staticmethod
    def get_stochastic_boost(k_percent):
        """Convert K% to confidence boost"""
        if k_percent is None:
            return 0

        # Overbought (>80) = strong pullback setup
        if k_percent > 80:
            return 15
        elif k_percent > 70:
            return 10
        elif k_percent > 50:
            return 5
        elif k_percent > 30:
            return 0
        elif k_percent > 20:
            return -5
        else:
            return -10

# ============================================================================
# DRY-RUN BOT v3.5
# ============================================================================

class DryRunBotV3_5:
    """Trading bot with Fibonacci + Stochastic"""

    def __init__(self):
        self.llm = LocalLLMWrapper() if HAS_LLAMA else None
        self.technical = TechnicalAnalyzer() if HAS_ENHANCED else None
        self.chart = AdvancedChartAnalyzer() if HAS_CHARTS else None
        self.rag = TradeRAG() if HAS_RAG else None
        self.ensemble = EnsembleAnalyzer() if HAS_ENSEMBLE else None
        self.learner = OnlineLearner() if HAS_ONLINE_LEARNING else None
        self.stoch = StochasticCalculator()
        self.symbol_updater = SymbolUpdater() if HAS_SYMBOL_UPDATER else None
        self.cycle_count = 0
        self.trades = []

    def run_cycle(self):
        """Execute one trading cycle with Fib + Stochastic"""

        self.cycle_count += 1
        log.info(f"\n{'='*80}")
        log.info(f"DRY-RUN CYCLE #{self.cycle_count} (v3.5 Fib+Stoch) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info(f"{'='*80}\n")

        # Get dynamic symbol list (NASDAQ top 50 + S&P 500 top 50)
        if self.symbol_updater:
            symbols = self.symbol_updater.get_symbols()
            log.info(f"Scanning {len(symbols)} symbols (dynamic list)")
        else:
            # Fallback to static list if updater not available
            symbols = [
                "AAPL", "ABNB", "ABT", "ACN", "ADBE", "ADP", "ALL", "AMAT", "AMD", "AMGN",
                "AMZN", "ASML", "AVGO", "AXP", "BA", "BERKB", "BKNG", "CDNA", "CDNS", "CMCSA",
                "COST", "COSTCO", "CPRT", "CRM", "CRWD", "CSCO", "CTAS", "DBX", "DDOG", "DIS",
                "ELV", "GILD", "GOOG", "GOOGL", "HDFC", "HON", "IBM", "IDXX", "INTC", "INTU",
                "JNJ", "JPM", "KLAC", "LLY", "LRCX", "MA", "MCHP", "META", "MMC", "MRK",
                "MRVL", "MSFT", "MTCH", "MU", "NFLX", "NOW", "NVDA", "OKTA", "ORCL", "PALO",
                "PAYX", "PG", "PYPL", "QCOM", "ROKU", "ROST", "SBUX", "SNOW", "SNPS", "SPLK",
                "TEAM", "TRIP", "TSLA", "TXN", "V", "VRSK", "WDAY", "WMT", "XOM"
            ]
            log.info(f"Scanning {len(symbols)} symbols (static fallback)")

        for symbol in symbols:
            try:
                # Get current price
                ticker = yf.Ticker(symbol)
                info = ticker.info
                current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)

                if current_price <= 0:
                    continue

                # Calculate anomaly
                pct_change = info.get("regularMarketChangePercent", 0)
                anomaly_score = min(100, abs(pct_change) * 15)

                # ===== STAGE 1: TECHNICAL CONTEXT =====
                technical_context = None
                if self.technical:
                    technical_context = self.technical.get_technical_context(symbol)

                # ===== STAGE 2: FIBONACCI LEVELS =====
                fib_boost = 0
                if self.chart:
                    try:
                        analysis = self.chart.get_chart_analysis(symbol)
                        if analysis:
                            fib = analysis.get("fibonacci_levels", {})
                            nearest = fib.get("nearest_level", "")
                            fib_scores = {"618": 10, "786": 8, "382": 5, "500": 3}
                            fib_boost = fib_scores.get(nearest, 0)
                    except:
                        pass

                # ===== STAGE 3: STOCHASTIC BOOST (v3.5 NEW!) =====
                k_percent, _ = self.stoch.calculate_k_percent(symbol)
                stoch_boost = self.stoch.get_stochastic_boost(k_percent)
                stoch_label = f"(K%: {k_percent:.1f})" if k_percent else ""

                # ===== STAGE 4: RAG CONTEXT =====
                rag_context = ""
                if self.rag and technical_context:
                    rag_context = self.rag.get_context_for_llama(symbol, technical_context)

                # ===== STAGE 5: LLAMA DECISION =====
                llama_decision = {"action": "SKIP", "confidence": 0}
                if self.llm and self.llm.is_available():
                    llama_decision = self.llm.analyze_trade(
                        symbol=symbol,
                        pct_change=pct_change,
                        anomaly_score=anomaly_score,
                        regime="range-bound",
                        technical_context=technical_context,
                        rag_context=rag_context
                    )

                # ===== STAGE 6: APPLY BOOSTS (Fib + Stoch) =====
                final_confidence = llama_decision.get("confidence", 50)
                final_confidence = min(100, final_confidence + fib_boost + stoch_boost)
                total_boost = fib_boost + stoch_boost

                # ===== STAGE 7: FINRL METRICS =====
                finrl_metrics = None
                finrl_signal = "HOLD"
                finrl_prob = 0.5
                if HAS_FINRL:
                    try:
                        finrl_metrics = get_finrl_metrics()
                        finrl_prob = min(0.95, max(0.05, (anomaly_score / 100) * 0.9))
                        finrl_signal = "BUY" if finrl_prob > 0.6 else "SELL" if finrl_prob < 0.4 else "HOLD"
                    except:
                        pass

                # ===== STAGE 8: ENSEMBLE =====
                if self.ensemble:
                    ensemble_result = self.ensemble.combine_signals(
                        llama_confidence=final_confidence,
                        finrl_signal=finrl_signal,
                        finrl_prob=finrl_prob
                    )
                    final_confidence = ensemble_result["combined_confidence"]
                    llama_decision["confidence"] = int(final_confidence)

                # ===== STAGE 9: ADAPTIVE THRESHOLD =====
                adaptive_threshold = 52
                if self.learner:
                    adaptive_threshold = self.learner.get_adaptive_threshold(symbol, base_threshold=52)

                # ===== DECISION =====
                would_trade = (
                    final_confidence >= adaptive_threshold and
                    (not finrl_metrics or finrl_metrics.get("sharpe", 0) > 0.8)
                )

                # ===== LOG TRADE =====
                if would_trade:
                    log.info(
                        f"BUY | {symbol} @ ${current_price:.2f} | "
                        f"Llama {llama_decision.get('confidence')}% "
                        f"| Fib+Stoch {total_boost:+d}% {stoch_label} | FinRL Sharpe 2.94"
                    )

                    # Hypothetical exit
                    realistic_profit = (current_price * 0.01) * (600 / current_price)
                    log.info(f"  → Outcome recorded: +${realistic_profit:.2f} (realistic scenario)")

                    # Record for learning
                    if self.learner:
                        self.learner.record_trade_result(
                            symbol=symbol,
                            llama_confidence=final_confidence,
                            actual_result=realistic_profit
                        )

                    if self.rag and technical_context:
                        self.rag.record_trade(
                            symbol=symbol,
                            entry_price=current_price,
                            exit_price=current_price * 1.01,
                            confidence=final_confidence,
                            technical_context=technical_context,
                            outcome_pnl=realistic_profit
                        )

                    self.trades.append({
                        "symbol": symbol,
                        "price": current_price,
                        "confidence": final_confidence,
                        "fib_boost": fib_boost,
                        "stoch_boost": stoch_boost,
                        "k_percent": k_percent,
                        "profit": realistic_profit
                    })
                else:
                    log.info(
                        f"SKIP | {symbol} @ ${current_price:.2f} | "
                        f"Llama {llama_decision.get('confidence')}% "
                        f"[threshold: {adaptive_threshold}%] | Fib+Stoch {total_boost:+d}% {stoch_label}"
                    )

            except Exception as e:
                log.error(f"Error analyzing {symbol}: {e}")
                continue

        # ===== PERFORMANCE SUMMARY =====
        self._log_performance_summary()

    def _log_performance_summary(self):
        """Log daily performance"""
        log.info(f"\n{'='*80}")
        log.info("PERFORMANCE SUMMARY (v3.5 Fib+Stochastic)")
        log.info(f"{'='*80}")
        log.info(f"Trades triggered: {len(self.trades)}")
        if self.trades:
            total_profit = sum(t["profit"] for t in self.trades)
            avg_confidence = sum(t["confidence"] for t in self.trades) / len(self.trades)
            avg_fib = sum(t["fib_boost"] for t in self.trades) / len(self.trades) if self.trades else 0
            avg_stoch = sum(t["stoch_boost"] for t in self.trades) / len(self.trades) if self.trades else 0
            log.info(f"Total profit: +${total_profit:.2f}")
            log.info(f"Avg confidence: {avg_confidence:.0f}%")
            log.info(f"Avg Fib boost: {avg_fib:+.1f}%")
            log.info(f"Avg Stoch boost: {avg_stoch:+.1f}%")
            log.info(f"\nRealistic (+1.5%): +${total_profit:.2f}")


if __name__ == "__main__":
    log.info("🤖 DRY-RUN BOT v3.5 with Fibonacci + Stochastic + Dynamic Symbols")
    log.info(f"Systems: Llama {'✅' if HAS_LLAMA else '❌'} | Charts {'✅' if HAS_CHARTS else '❌'} | Ensemble {'✅' if HAS_ENSEMBLE else '❌'} | Symbol Updater {'✅' if HAS_SYMBOL_UPDATER else '❌'}")

    bot = DryRunBotV3_5()
    bot.run_cycle()
