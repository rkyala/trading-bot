#!/usr/bin/env python3
"""
DRY-RUN MODE: Logs all analysis without placing orders
- Tests Llama 2 + FinRL + News Sentiment
- Tracks hypothetical trades
- Logs entry/exit prices
- Calculates would-be returns
- Safe validation before live trading
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
import pytz
import time
import requests
import yfinance as yf

# Local imports
try:
    from local_llm_wrapper import LocalLLMWrapper
    HAS_LLAMA = True
except ImportError:
    HAS_LLAMA = False
    print("⚠️  Llama 2 not available (use rule-based fallback)")

try:
    from finrl_integration import get_finrl_metrics
    HAS_FINRL = True
except ImportError:
    HAS_FINRL = False
    print("⚠️  FinRL not available")

try:
    from news_fetcher import NewsFetcher
    from news_sentiment import NewsSentimentAnalyzer
    HAS_SENTIMENT = True
except ImportError:
    HAS_SENTIMENT = False
    print("⚠️  News sentiment not available")

try:
    from online_learning import OnlineLearner
    HAS_ONLINE_LEARNING = True
except ImportError:
    HAS_ONLINE_LEARNING = False
    print("⚠️  Online learning not available")

try:
    from enhanced_analysis import TechnicalAnalyzer
    HAS_ENHANCED = True
except ImportError:
    HAS_ENHANCED = False
    print("⚠️  Enhanced analysis not available")

try:
    from rag_trades import TradeRAG
    HAS_RAG = True
except ImportError:
    HAS_RAG = False
    print("⚠️  RAG system not available")

try:
    from ensemble import EnsembleAnalyzer
    HAS_ENSEMBLE = True
except ImportError:
    HAS_ENSEMBLE = False
    print("⚠️  Ensemble system not available")

# ============================================================================
# CONFIGURATION
# ============================================================================

DRY_RUN_MODE = True
LOG_DIR = "dry_run_logs"
ANALYSIS_LOG = os.path.join(LOG_DIR, f"analysis_{datetime.now().strftime('%Y%m%d')}.jsonl")
PERFORMANCE_LOG = os.path.join(LOG_DIR, f"performance_{datetime.now().strftime('%Y%m%d')}.json")

# Create log directory
os.makedirs(LOG_DIR, exist_ok=True)

# Setup logging
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
# DRY-RUN LOGGER
# ============================================================================

class DryRunLogger:
    """Log all analysis decisions without executing trades"""

    def __init__(self, log_file=ANALYSIS_LOG):
        self.log_file = log_file
        self.trades = []  # Track hypothetical trades
        self.cycle_count = 0
        self.learner = OnlineLearner() if HAS_ONLINE_LEARNING else None

    def log_analysis(self, symbol, llama_decision, finrl_metrics, sentiment_data, current_price):
        """Log one symbol's complete analysis"""

        # Get adaptive confidence threshold based on past performance
        # Lower base threshold to encourage more diverse trades
        adaptive_threshold = 52  # Lowered from 60 for better coverage
        if self.learner:
            adaptive_threshold = self.learner.get_adaptive_threshold(symbol, base_threshold=52)

        analysis = {
            "timestamp": datetime.now(pytz.UTC).isoformat(),
            "cycle": self.cycle_count,
            "symbol": symbol,
            "current_price": current_price,

            # Llama 2 Analysis
            "llama2": {
                "decision": llama_decision.get("action", "UNKNOWN"),
                "confidence": llama_decision.get("confidence", 0),
                "reason": llama_decision.get("reason", ""),
            },

            # FinRL Metrics
            "finrl": {
                "sharpe": finrl_metrics.get("sharpe", 0) if finrl_metrics else None,
                "annual_return": finrl_metrics.get("annual_return", 0) if finrl_metrics else None,
            },

            # News Sentiment
            "sentiment": {
                "sentiment_type": sentiment_data.get("sentiment", "N/A"),
                "confidence": sentiment_data.get("confidence", 0),
            },

            # Online Learning
            "adaptive_threshold": adaptive_threshold,

            # Decision (using adaptive threshold - lowered for diversity)
            "would_trade": (
                llama_decision.get("confidence", 0) >= adaptive_threshold and
                (not finrl_metrics or finrl_metrics.get("sharpe", 0) > 0.8)  # Lowered Sharpe filter too
            ),
        }

        # Write to log file (JSONL format)
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(analysis) + '\n')

        sharpe_str = f"{analysis['finrl']['sharpe']:.2f}" if analysis['finrl']['sharpe'] else 'N/A'
        threshold_str = f"[threshold: {adaptive_threshold}%]" if adaptive_threshold != 60 else ""
        log.info(
            f"{'BUY' if analysis['would_trade'] else 'SKIP'} | "
            f"{symbol} @ ${current_price:.2f} | "
            f"Llama {analysis['llama2']['confidence']}% {threshold_str} | "
            f"Sentiment {analysis['sentiment']['sentiment_type']} | "
            f"FinRL Sharpe {sharpe_str}"
        )

        return analysis

    def log_hypothetical_trade(self, analysis, entry_price, target_prices=[0.01, 0.02, 0.03], stop_loss=-0.015):
        """Log what WOULD happen if we traded this"""

        if not analysis["would_trade"]:
            return

        trade = {
            "timestamp": analysis["timestamp"],
            "symbol": analysis["symbol"],
            "entry_price": entry_price,
            "position_size": 600,  # Assume $600 per position
            "quantity": int(600 / entry_price),
            "confidence": analysis["llama2"]["confidence"],
        }

        # Calculate hypothetical exits
        exits = {}
        for target_pct in target_prices:
            exit_price = entry_price * (1 + target_pct)
            profit = (exit_price - entry_price) * trade["quantity"]
            exits[f"+{int(target_pct*100)}%"] = {
                "price": exit_price,
                "profit": profit,
                "roi": (profit / 600) * 100
            }

        # Calculate stop loss
        stop_price = entry_price * (1 + stop_loss)
        stop_profit = (stop_price - entry_price) * trade["quantity"]
        exits["stop_loss"] = {
            "price": stop_price,
            "profit": stop_profit,
            "roi": (stop_profit / 600) * 100
        }

        trade["hypothetical_exits"] = exits
        self.trades.append(trade)

        return trade

    def save_performance_summary(self):
        """Calculate and save daily performance summary"""

        if not self.trades:
            log.info("No trades analyzed today")
            return

        summary = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_analyzed": len(self.trades),
            "trades_that_would_execute": sum(1 for t in self.trades if t),

            # Performance metrics
            "best_case_scenario": {
                "target": "+3%",
                "total_profit": sum(t["hypothetical_exits"]["+3%"]["profit"] for t in self.trades),
                "total_roi": sum(t["hypothetical_exits"]["+3%"]["roi"] for t in self.trades) / len(self.trades) if self.trades else 0,
            },

            "realistic_scenario": {
                "target": "+1.5%",
                "total_profit": sum(t["hypothetical_exits"]["+1%"]["profit"] for t in self.trades),
                "total_roi": sum(t["hypothetical_exits"]["+1%"]["roi"] for t in self.trades) / len(self.trades) if self.trades else 0,
            },

            "conservative_scenario": {
                "target": "stop_loss",
                "total_profit": sum(t["hypothetical_exits"]["stop_loss"]["profit"] for t in self.trades),
                "total_roi": sum(t["hypothetical_exits"]["stop_loss"]["roi"] for t in self.trades) / len(self.trades) if self.trades else 0,
            },

            "trades": self.trades,
        }

        # Save summary
        with open(PERFORMANCE_LOG, 'w') as f:
            json.dump(summary, f, indent=2)

        log.info(f"\n{'='*80}")
        log.info("DRY-RUN PERFORMANCE SUMMARY")
        log.info(f"{'='*80}")
        log.info(f"Trades analyzed: {summary['total_analyzed']}")
        log.info(f"Would execute: {summary['trades_that_would_execute']}")
        log.info(f"\nBest case (+3%): ${summary['best_case_scenario']['total_profit']:.2f} ({summary['best_case_scenario']['total_roi']:.2f}%)")
        log.info(f"Realistic (+1.5%): ${summary['realistic_scenario']['total_profit']:.2f} ({summary['realistic_scenario']['total_roi']:.2f}%)")
        log.info(f"Conservative (stop): ${summary['conservative_scenario']['total_profit']:.2f} ({summary['conservative_scenario']['total_roi']:.2f}%)")
        log.info(f"{'='*80}\n")

        return summary


# ============================================================================
# DRY-RUN BOT
# ============================================================================

class DryRunBot:
    """Run trading analysis without executing trades + enhanced systems"""

    def __init__(self):
        self.llm = LocalLLMWrapper() if HAS_LLAMA else None
        self.fetcher = NewsFetcher() if HAS_SENTIMENT else None
        self.analyzer = NewsSentimentAnalyzer() if HAS_SENTIMENT else None
        self.logger = DryRunLogger()
        self.learner = self.logger.learner  # Share learner instance

        # NEW: Enhanced analysis systems
        self.technical = TechnicalAnalyzer() if HAS_ENHANCED else None
        self.rag = TradeRAG() if HAS_RAG else None
        self.ensemble = EnsembleAnalyzer(llama_weight=0.6, finrl_weight=0.4) if HAS_ENSEMBLE else None

    def run_cycle(self):
        """Run one analysis cycle"""

        self.logger.cycle_count += 1
        log.info(f"\n{'='*80}")
        log.info(f"DRY-RUN CYCLE #{self.logger.cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log.info(f"{'='*80}\n")

        # Get top movers - EXPANDED watchlist for diversity
        symbols = [
            # Semiconductors (mean-reversion friendly)
            "INTC", "AMD", "NVDA", "MU",
            # Tech & Value mix
            "AAPL", "META", "QCOM", "TSLA"
        ]

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

                # ===== NEW: GET TECHNICAL CONTEXT =====
                technical_context = None
                if self.technical:
                    technical_context = self.technical.get_technical_context(symbol)

                # ===== NEW: GET RAG CONTEXT (PAST TRADES) =====
                rag_context = ""
                if self.rag and technical_context:
                    rag_context = self.rag.get_context_for_llama(symbol, technical_context)

                # ===== STAGE 1: ENHANCED LLAMA DECISION =====
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

                # ===== STAGE 2: FINRL METRICS =====
                finrl_metrics = None
                finrl_signal = "HOLD"
                finrl_prob = 0.5
                if HAS_FINRL:
                    try:
                        finrl_metrics = get_finrl_metrics()
                        # Extract signal from FinRL (simplified)
                        finrl_prob = min(0.95, max(0.05, (anomaly_score / 100) * 0.9))
                        finrl_signal = "BUY" if finrl_prob > 0.6 else "SELL" if finrl_prob < 0.4 else "HOLD"
                    except:
                        pass

                # ===== NEW: ENSEMBLE COMBINATION =====
                ensemble_result = None
                final_confidence = llama_decision.get("confidence", 50)
                if self.ensemble:
                    ensemble_result = self.ensemble.combine_signals(
                        llama_confidence=final_confidence,
                        finrl_signal=finrl_signal,
                        finrl_prob=finrl_prob
                    )
                    final_confidence = ensemble_result["combined_confidence"]
                    llama_decision["confidence"] = int(final_confidence)
                    llama_decision["ensemble_reasoning"] = ensemble_result["reasoning"]

                # ===== STAGE 1B: NEWS SENTIMENT =====
                sentiment_data = {"sentiment": "NEUTRAL", "confidence": 0}
                if self.fetcher and self.analyzer:
                    try:
                        news = self.fetcher.get_latest_news(symbol, max_articles=2)
                        if news:
                            full_text = " ".join([n["title"] + " " + n["summary"] for n in news])
                            sentiment_data = self.analyzer.analyze(full_text)
                    except:
                        pass

                # ===== LOG ANALYSIS =====
                analysis = self.logger.log_analysis(
                    symbol=symbol,
                    llama_decision=llama_decision,
                    finrl_metrics=finrl_metrics,
                    sentiment_data=sentiment_data,
                    current_price=current_price
                )

                # ===== LOG HYPOTHETICAL TRADE =====
                if analysis["would_trade"]:
                    trade = self.logger.log_hypothetical_trade(analysis, entry_price=current_price)
                    if trade:
                        log.info(f"  → Hypothetical trade logged for {symbol}")
                        if ensemble_result:
                            log.info(f"    {ensemble_result['reasoning']}")

                        # ===== RECORD OUTCOME FOR RAG & ONLINE LEARNING =====
                        # For dry-run, assume realistic scenario (+1% exit)
                        if self.learner:
                            realistic_profit = trade["hypothetical_exits"]["+1%"]["profit"]
                            self.learner.record_trade_result(
                                symbol=symbol,
                                llama_confidence=trade["confidence"],
                                actual_result=realistic_profit
                            )
                            log.info(f"  → Outcome recorded: +${realistic_profit:.2f} (realistic scenario)")

                        # Record in RAG for future learning
                        if self.rag and technical_context:
                            self.rag.record_trade(
                                symbol=symbol,
                                entry_price=current_price,
                                exit_price=current_price * 1.01,  # Realistic +1%
                                confidence=trade["confidence"],
                                technical_context=technical_context,
                                outcome_pnl=realistic_profit
                            )

            except Exception as e:
                log.error(f"Error analyzing {symbol}: {e}")
                continue

        # Save performance summary
        self.logger.save_performance_summary()

        # Print adaptive thresholds summary
        if self.learner:
            log.info(f"\n{'='*80}")
            log.info("ADAPTIVE THRESHOLDS (Online Learning)")
            log.info(f"{'='*80}")
            for symbol in ["INTC", "AMD", "NVDA", "MSFT", "TSLA"]:
                win_rate = self.learner.get_win_rate(symbol)
                threshold = self.learner.get_adaptive_threshold(symbol, base_threshold=60)
                if win_rate is not None:
                    win_rate_pct = win_rate * 100
                    log.info(f"{symbol}: Win rate {win_rate_pct:.1f}% → Threshold {threshold}%")
            log.info(f"{'='*80}\n")


# ============================================================================
# MAIN
# ============================================================================

def main():
    log.info("="*80)
    log.info("DRY-RUN MODE: No orders will be placed")
    log.info(f"Logs: {LOG_DIR}/")
    log.info("="*80)

    bot = DryRunBot()
    bot.run_cycle()


if __name__ == "__main__":
    main()
