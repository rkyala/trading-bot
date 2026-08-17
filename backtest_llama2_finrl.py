#!/usr/bin/env python3
"""
Backtest: Llama 2 7B + FinRL for Zero-Cost Trading
Tests hybrid approach: Local LLM reasoning + FinRL predictions
"""

import json
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf

# Try to load FinRL model (optional)
try:
    from finrl_integration import load_finrl_model
    HAS_FINRL = True
except:
    HAS_FINRL = False
    print("⚠️  FinRL not available (optional)")

try:
    from local_llm_wrapper import LocalLLMWrapper
    HAS_LLAMA = True
except:
    HAS_LLAMA = False
    print("⚠️  Llama wrapper not available")

# ============================================================================
# BACKTEST ENGINE
# ============================================================================

class HybridBacktest:
    """Backtest Llama 2 + FinRL strategy"""

    def __init__(self, symbols, start_date, end_date, initial_capital=10000):
        """Initialize backtest"""
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self.initial = initial_capital
        self.cash = initial_capital
        self.positions = {}
        self.trades = []
        self.portfolio_values = [initial_capital]

        # Load models
        self.llm = LocalLLMWrapper() if HAS_LLAMA else None
        self.finrl_model = load_finrl_model() if HAS_FINRL else None

        # Download data
        print(f"\n📊 Downloading {len(symbols)} stocks ({(end_date - start_date).days} days)...\n")
        self.data = {}
        for s in symbols:
            try:
                df = yf.download(s, start=start_date, end=end_date, progress=False)
                if not df.empty and len(df) > 50:
                    self.data[s] = df
                    print(f"   ✓ {s}: {len(df)} bars")
            except:
                print(f"   ✗ {s}: Failed to download")

        if len(self.data) < 3:
            print("\n❌ Not enough data. Exiting.")
            sys.exit(1)

    def calculate_mean_reversion_signal(self, symbol, prices, window=20):
        """Calculate mean-reversion signal"""
        if len(prices) < window:
            return None

        mean = np.mean(prices[-window:])
        current = prices[-1]
        pct_change = ((current - mean) / mean) * 100

        # Anomaly score: how far from mean (0-100 scale)
        std = np.std(prices[-window:])
        z_score = abs(pct_change) / (std / mean * 100 + 1e-6)
        anomaly = min(100, z_score * 20)

        return {
            "symbol": symbol,
            "price": current,
            "mean": mean,
            "pct_change": pct_change,
            "anomaly_score": anomaly,
            "regime": self._detect_regime(prices[-window:]),
        }

    def _detect_regime(self, prices):
        """Detect market regime"""
        sma_short = np.mean(prices[-5:])
        sma_long = np.mean(prices[-20:])
        trend = (sma_short - sma_long) / sma_long * 100

        if trend > 1:
            return "trending_up"
        elif trend < -1:
            return "trending_down"
        else:
            return "range-bound"

    def get_decision_llama(self, signal):
        """Get LLM decision"""
        if not self.llm or not self.llm.is_available():
            return None

        return self.llm.analyze_trade(
            symbol=signal["symbol"],
            pct_change=signal["pct_change"],
            anomaly_score=signal["anomaly_score"],
            regime=signal["regime"],
        )

    def get_decision_finrl(self, signal):
        """Get FinRL decision (placeholder for now)"""
        if not self.finrl_model:
            return None

        # FinRL would return a confidence score 0-1
        # For now, use simple confidence based on signal strength
        confidence = min(0.95, (signal["anomaly_score"] / 100) * 0.9 + 0.2)

        return {
            "action": "BUY" if signal["pct_change"] > 2 else "SKIP",
            "confidence": int(confidence * 100),
            "reason": f"FinRL: {confidence:.0%}",
        }

    def run_backtest(self):
        """Run full backtest"""
        print("="*70)
        print("  BACKTEST: Llama 2 + FinRL Hybrid Strategy")
        print("="*70 + "\n")

        # Get date range
        all_dates = []
        for s in self.data:
            all_dates.extend(self.data[s].index.tolist())
        all_dates = sorted(set(all_dates))

        total_trades = 0
        wins = 0
        losses = 0

        # Simulate day by day
        for day_idx in range(20, len(all_dates)):
            date = all_dates[day_idx]

            # Scan for signals
            signals = []
            for symbol in self.symbols:
                if symbol not in self.data:
                    continue

                df = self.data[symbol]
                mask = df.index <= date
                if len(df[mask]) < 20:
                    continue

                prices = df[mask]["Close"].values
                signal = self.calculate_mean_reversion_signal(symbol, prices)
                if signal and abs(signal["pct_change"]) > 2:
                    signals.append(signal)

            if not signals:
                continue

            # Get decisions for top signals
            for signal in sorted(signals, key=lambda x: x["anomaly_score"], reverse=True)[:3]:
                # Get both LLM and FinRL opinions
                llm_decision = self.get_decision_llama(signal)
                finrl_decision = self.get_decision_finrl(signal)

                # Hybrid decision: require agreement
                llm_yes = llm_decision and llm_decision.get("action") == "BUY"
                finrl_yes = finrl_decision and finrl_decision.get("action") == "BUY"
                llm_conf = llm_decision.get("confidence", 0) if llm_decision else 0
                finrl_conf = finrl_decision.get("confidence", 0) if finrl_decision else 0

                # Trade if BOTH agree or high confidence from LLM
                if llm_yes and (finrl_yes or llm_conf > 75):
                    # Execute trade
                    symbol = signal["symbol"]
                    price = signal["price"]
                    qty = int((self.cash * 0.2) / price)  # 20% of cash per trade

                    if qty > 0 and self.cash >= qty * price:
                        self.cash -= qty * price
                        self.positions[symbol] = qty
                        total_trades += 1

                        self.trades.append({
                            "date": date,
                            "symbol": symbol,
                            "action": "BUY",
                            "qty": qty,
                            "price": price,
                            "llm_conf": llm_conf,
                            "finrl_conf": finrl_conf,
                        })

                        print(f"  💰 BUY {symbol}: {qty} @ ${price:.2f} | LLM {llm_conf}% | FinRL {finrl_conf}%")

            # Close winning positions
            for symbol in list(self.positions.keys()):
                if symbol not in self.data:
                    continue

                df = self.data[symbol]
                mask = df.index <= date
                if len(df[mask]) < 1:
                    continue

                current_price = df[mask]["Close"].values[-1]
                entry_price = self.trades[-1]["price"] if self.trades and self.trades[-1]["symbol"] == symbol else 0

                if entry_price > 0:
                    pnl_pct = (current_price - entry_price) / entry_price

                    # Close if 3% profit or 1% loss
                    if pnl_pct > 0.03 or pnl_pct < -0.01:
                        proceeds = self.positions[symbol] * current_price
                        self.cash += proceeds
                        pnl = proceeds - (self.positions[symbol] * entry_price)

                        if pnl > 0:
                            wins += 1
                        else:
                            losses += 1

                        print(f"  ✅ SELL {symbol}: +{pnl_pct*100:.1f}% | P&L ${pnl:+.0f}")
                        del self.positions[symbol]

            # Portfolio value
            portfolio = self.cash
            for symbol, qty in self.positions.items():
                if symbol in self.data:
                    df = self.data[symbol]
                    mask = df.index <= date
                    if len(df[mask]) > 0:
                        current_price = df[mask]["Close"].values[-1]
                        portfolio += qty * current_price

            self.portfolio_values.append(portfolio)

        # Close all remaining positions at end
        if len(all_dates) > 0:
            end_date = all_dates[-1]
            for symbol in list(self.positions.keys()):
                if symbol in self.data:
                    current_price = self.data[symbol][self.data[symbol].index <= end_date]["Close"].values[-1]
                    proceeds = self.positions[symbol] * current_price
                    self.cash += proceeds

        print("\n" + "="*70)
        print("  RESULTS")
        print("="*70)

        pv = np.array(self.portfolio_values)
        final = pv[-1]
        total_ret = (final - self.initial) / self.initial * 100
        annual_ret = total_ret * (252 / len(pv)) if len(pv) > 1 else 0

        if len(pv) > 1:
            rets = np.diff(pv) / pv[:-1]
            sharpe = (np.mean(rets) / (np.std(rets) + 1e-8)) * np.sqrt(252)
            dd = np.min((pv - np.maximum.accumulate(pv)) / np.maximum.accumulate(pv)) * 100
        else:
            sharpe = 0
            dd = 0

        print(f"\nFinal Value:        ${final:,.0f}")
        print(f"Total Return:       {total_ret:+.2f}%")
        print(f"Annualized:         {annual_ret:+.2f}%")
        print(f"Sharpe Ratio:       {sharpe:.2f}")
        print(f"Max Drawdown:       {dd:.2f}%")
        print(f"\nTrades Executed:    {total_trades}")
        print(f"Wins:               {wins}")
        print(f"Losses:             {losses}")
        print(f"Win Rate:           {(wins/(wins+losses)*100 if wins+losses > 0 else 0):.1f}%")
        print("\n" + "="*70 + "\n")

        return {
            "final_value": final,
            "total_return": total_ret,
            "annualized": annual_ret,
            "sharpe": sharpe,
            "max_dd": dd,
            "trades": total_trades,
            "wins": wins,
            "losses": losses,
        }


# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("  ZERO-COST HYBRID BACKTEST: Llama 2 + FinRL")
    print("="*70)

    # Config
    SYMBOLS = ["INTC", "AMD", "NVDA", "LRCX", "AVGO", "KEYS"]
    END_DATE = datetime.now()
    START_DATE = END_DATE - timedelta(days=180)  # 6 months

    # Check if Llama is available
    llm = LocalLLMWrapper()
    if not llm.is_available():
        print("\n⚠️  Ollama server not running!")
        print("   Start with: OLLAMA_FLASH_ATTENTION=1 ollama serve")
        sys.exit(1)

    # Run backtest
    bt = HybridBacktest(SYMBOLS, START_DATE, END_DATE)
    results = bt.run_backtest()

    # Save results
    with open("backtest_llama2_finrl_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("✅ Results saved to backtest_llama2_finrl_results.json")
