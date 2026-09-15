#!/usr/bin/env python3
"""
KPI Tracker: 30-Day Validation Period (Aug 26 - Sep 30)
Tracks metrics to unlock $50K scaling decision
"""

import json
from datetime import datetime
from pathlib import Path

class KPITracker:
    """Track KPIs for Sept 1 scaling decision"""

    def __init__(self):
        self.kpi_file = "kpi_tracking.json"
        self.kpis = self._load_or_create()

    def _load_or_create(self):
        """Load existing KPIs or create new"""
        if Path(self.kpi_file).exists():
            with open(self.kpi_file, "r") as f:
                return json.load(f)

        return {
            "launch_date": "2026-08-26",
            "validation_end_date": "2026-09-30",
            "account_size": 10000,
            "position_size": 50,
            "trades": [],
            "metrics": {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "peak_equity": 10000,
                "min_equity": 10000,
                "max_drawdown_pct": 0.0,
                "avg_slippage_pct": 0.0,
                "circuit_breaker_resets": 0,
                "state_persistence_issues": 0,
            },
            "status": "INITIALIZING"
        }

    def log_trade(self, symbol, entry_price, exit_price, signal_price, pnl_dollars, pnl_pct, is_win):
        """Log a completed trade"""
        slippage = abs(entry_price - signal_price) / signal_price * 100

        trade = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "signal_price": signal_price,
            "slippage_pct": slippage,
            "pnl_dollars": pnl_dollars,
            "pnl_pct": pnl_pct,
            "is_win": is_win
        }

        self.kpis["trades"].append(trade)
        self._update_metrics()
        self._save()

    def _update_metrics(self):
        """Recalculate all metrics"""
        trades = self.kpis["trades"]

        if not trades:
            return

        # Win rate
        self.kpis["metrics"]["total_trades"] = len(trades)
        self.kpis["metrics"]["winning_trades"] = sum(1 for t in trades if t["is_win"])
        self.kpis["metrics"]["losing_trades"] = len(trades) - self.kpis["metrics"]["winning_trades"]

        win_rate = self.kpis["metrics"]["winning_trades"] / len(trades)
        self.kpis["metrics"]["win_rate"] = win_rate * 100

        # Equity tracking
        running_equity = 10000
        for trade in trades:
            running_equity += trade["pnl_dollars"]
            self.kpis["metrics"]["peak_equity"] = max(self.kpis["metrics"]["peak_equity"], running_equity)
            self.kpis["metrics"]["min_equity"] = min(self.kpis["metrics"]["min_equity"], running_equity)

        # Drawdown
        drawdown = (self.kpis["metrics"]["peak_equity"] - self.kpis["metrics"]["min_equity"]) / self.kpis["metrics"]["peak_equity"]
        self.kpis["metrics"]["max_drawdown_pct"] = drawdown * 100

        # Slippage
        slippages = [t["slippage_pct"] for t in trades]
        self.kpis["metrics"]["avg_slippage_pct"] = sum(slippages) / len(slippages)

    def _save(self):
        """Save KPIs to file"""
        with open(self.kpi_file, "w") as f:
            json.dump(self.kpis, f, indent=2)

    def get_validation_status(self):
        """Check if KPIs meet Sept 1 scaling criteria"""
        metrics = self.kpis["metrics"]
        total = metrics["total_trades"]

        print("\n" + "="*100)
        print("KPI VALIDATION STATUS (Sep 1 Scaling Decision)")
        print("="*100)

        print(f"\n1️⃣  WIN-RATE ALIGNMENT")
        print(f"   Target: 21.9% - 24.1%")
        print(f"   Actual: {metrics['win_rate']:.1f}%")

        if total >= 50:
            if 21.9 <= metrics["win_rate"] <= 24.1:
                print(f"   ✅ PASS ({total} trades)")
            else:
                print(f"   ⚠️  CAUTION ({total} trades, outside band)")
        else:
            print(f"   ⏳ IN PROGRESS ({total}/50 trades needed)")

        print(f"\n2️⃣  SLIPPAGE TOLERANCE")
        print(f"   Target: < 0.15% average")
        print(f"   Actual: {metrics['avg_slippage_pct']:.3f}%")

        if metrics["avg_slippage_pct"] < 0.15:
            print(f"   ✅ PASS (excellent execution)")
        else:
            print(f"   ⚠️  CAUTION (slippage acceptable but high)")

        print(f"\n3️⃣  STATE PERSISTENCE")
        print(f"   Target: Zero resets")
        print(f"   Circuit Breaker Resets: {self.kpis['metrics']['circuit_breaker_resets']}")
        print(f"   State Issues: {self.kpis['metrics']['state_persistence_issues']}")

        if self.kpis['metrics']['circuit_breaker_resets'] == 0 and self.kpis['metrics']['state_persistence_issues'] == 0:
            print(f"   ✅ PASS (state persists cleanly)")
        else:
            print(f"   ⚠️  CAUTION (some state issues detected)")

        print(f"\n4️⃣  DRAWDOWN BOUNDARY")
        print(f"   Target: < -14.5%")
        print(f"   Actual: {metrics['max_drawdown_pct']:+.1f}%")

        if metrics["max_drawdown_pct"] < 14.5:
            print(f"   ✅ PASS (drawdown controlled)")
        else:
            print(f"   ⚠️  CAUTION (drawdown exceeded tolerance)")

        print(f"\n" + "="*100)
        print("SEPT 1 SCALING DECISION")
        print("="*100)

        kpis_pass = (
            (total >= 50 and 21.9 <= metrics["win_rate"] <= 24.1) and
            metrics["avg_slippage_pct"] < 0.15 and
            self.kpis['metrics']['circuit_breaker_resets'] == 0 and
            metrics["max_drawdown_pct"] < 14.5
        )

        if kpis_pass:
            print(f"\n🟢 ALL KPIs MET - SCALE TO $50,000")
            print(f"   Ready to increase position size to 1% ($500/trade)")
            print(f"   Expected monthly P&L: $100-300 (+1-3%)")
        else:
            print(f"\n🟡 SOME KPIs PENDING - CONTINUE VALIDATION")
            print(f"   Keep running $10K account through Sep 30")
            print(f"   Reassess scaling decision by Sep 15")

        print("="*100 + "\n")

        return kpis_pass

if __name__ == "__main__":
    tracker = KPITracker()

    # Show status (this will auto-update as bot logs trades)
    tracker.get_validation_status()

    print("ℹ️  KPI Tracker Active")
    print("   File: kpi_tracking.json")
    print("   Bot will update this daily as trades execute")
    print("   Check status weekly: python3 kpi_tracker.py\n")
