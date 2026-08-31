#!/usr/bin/env python3
"""
Enhanced Alert Engine - SIMPLIFIED
Execution-only critical data + Options flow intelligence
"""

import numpy as np
import pandas as pd
import yfinance as yf
import logging

log = logging.getLogger(__name__)

class EnhancedAlertEngine:
    """Production alert generation - execution focus only + options flow intelligence"""

    # Execution gates - strict thresholds to prevent low-conviction trades
    MIN_RVOL = 1.25  # Institutional volume threshold
    MIN_CONFIDENCE = 65  # High-conviction score threshold

    def __init__(self, account_balance: float, risk_pct_per_trade: float = 1.0):
        self.account_balance = account_balance
        self.risk_pct_per_trade = risk_pct_per_trade
        self.risk_amount_per_trade = account_balance * (risk_pct_per_trade / 100.0)

    @staticmethod
    def get_options_metrics(symbol: str) -> dict:
        """Fetch options flow intelligence: P/C ratio, Vol/OI, IV (alerts only - no execution)"""
        try:
            # Skip futures (no options)
            if symbol.startswith("/"):
                return None

            ticker = yf.Ticker(symbol)
            expirations = ticker.options

            if not expirations or len(expirations) == 0:
                return None

            # Nearest expiration (typically ~7-30 days)
            nearest_exp = expirations[0]
            opt_chain = ticker.option_chain(nearest_exp)

            calls = opt_chain.calls
            puts = opt_chain.puts

            # Volume totals
            total_call_vol = float(calls['volume'].fillna(0).sum())
            total_put_vol = float(puts['volume'].fillna(0).sum())
            total_call_oi = float(calls['openInterest'].fillna(1).sum())

            # Put/Call Volume Ratio (PCR) - institutional sentiment
            pc_ratio = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

            # Call Volume / Call OI Ratio - unusual activity detection
            vol_oi_ratio = total_call_vol / total_call_oi if total_call_oi > 0 else 0.0

            # Average Implied Volatility (%)
            avg_iv = float(calls['impliedVolatility'].mean()) * 100 if len(calls) > 0 else 50.0

            return {
                "pc_ratio": round(pc_ratio, 2),
                "vol_oi_ratio": round(vol_oi_ratio, 2),
                "avg_iv": round(avg_iv, 1),
                "call_vol": int(total_call_vol),
                "put_vol": int(total_put_vol),
                "expiry": nearest_exp
            }

        except Exception as e:
            log.warning(f"Options metrics skipped for {symbol}: {e}")
            return None

    @staticmethod
    def select_options_strategy(entry_price: float, target_price: float, stop_price: float,
                               iv: float, pc_ratio: float, vol_oi: float) -> dict:
        """Select optimal options strategy based on IV, flow, and setup (alerts only)"""
        # Strike grid based on price level
        strike_grid = 2.5 if entry_price < 100 else (5.0 if entry_price < 300 else 10.0)

        # Near-the-money long strike
        long_strike = round(entry_price / strike_grid) * strike_grid
        # Target short strike for spreads
        short_strike = round(target_price / strike_grid) * strike_grid

        # Ensure spread width exists
        if short_strike <= long_strike:
            short_strike = long_strike + strike_grid

        # Strategy selection matrix
        if iv >= 60.0 and pc_ratio <= 0.65:
            # High IV Bullish
            return {
                "strategy": "Bull Call Debit Spread",
                "strikes": f"Buy ${long_strike:.2f}C / Sell ${short_strike:.2f}C",
                "rationale": "⚠️ High IV (crush risk) — spread offsets Vega"
            }
        elif iv < 60.0 and pc_ratio <= 0.8 and vol_oi > 1.5:
            # Low/Moderate IV Bullish with activity
            return {
                "strategy": "Long Call",
                "strikes": f"Buy ${long_strike:.2f}C (30-45 DTE)",
                "rationale": "✅ Moderate IV — directional delta setup"
            }
        elif iv >= 60.0 and pc_ratio > 1.2:
            # High IV Bearish
            return {
                "strategy": "Bear Put Debit Spread",
                "strikes": f"Buy ${long_strike:.2f}P / Sell ${short_strike:.2f}P",
                "rationale": "📉 High IV puts — downside vertical protection"
            }
        else:
            # High IV Neutral
            return {
                "strategy": "Bull Put Credit Spread",
                "strikes": f"Sell ${long_strike:.2f}P / Buy ${stop_price:.2f}P",
                "rationale": "🛡️ Volatility harvest — credit on support"
            }

    @staticmethod
    def interpret_options_flow(opt_metrics: dict) -> str:
        """Convert options metrics into human-readable flow interpretation"""
        if not opt_metrics:
            return ""

        pc = opt_metrics["pc_ratio"]
        vol_oi = opt_metrics["vol_oi_ratio"]
        iv = opt_metrics["avg_iv"]

        interpretations = []

        # P/C Ratio interpretation
        if pc < 0.6:
            interpretations.append("🔵 Bullish flow (heavy calls)")
        elif pc < 0.8:
            interpretations.append("🔵 Bullish leaning (calls > puts)")
        elif pc > 1.3:
            interpretations.append("🔴 Bearish flow (heavy puts)")
        elif pc > 1.0:
            interpretations.append("🔴 Bearish leaning (puts > calls)")
        else:
            interpretations.append("⚪ Neutral sentiment")

        # Vol/OI Ratio interpretation
        if vol_oi > 3.0:
            interpretations.append("⚡ Aggressive new positioning")
        elif vol_oi > 2.0:
            interpretations.append("📈 Heavy new volume")
        elif vol_oi > 1.0:
            interpretations.append("Normal volume activity")
        else:
            interpretations.append("Closing positions")

        # IV interpretation
        if iv < 35:
            interpretations.append("💰 Cheap options (good for buying)")
        elif iv < 50:
            interpretations.append("Moderate pricing")
        elif iv < 70:
            interpretations.append("🔥 Expensive options")
        else:
            interpretations.append("🔥 Very expensive (IV crush risk)")

        return " | ".join(interpretations)
    
    def calculate_dynamic_confidence(self, rvol: float, rsi: float, 
                                     price_above_ema20: bool, price_above_sma200: bool,
                                     entry_price: float, stop_loss: float, take_profit: float) -> int:
        """Calculate confidence (no hardcoded values)"""
        confidence = 50  # Base
        
        if rvol >= 2.5:
            confidence += 20
        elif rvol >= 2.0:
            confidence += 18
        elif rvol >= 1.5:
            confidence += 12
        
        if price_above_ema20 and price_above_sma200:
            confidence += 10
        elif price_above_ema20 or price_above_sma200:
            confidence += 5
        
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr = reward / risk if risk > 0 else 0
        
        if rr >= 2.5:
            confidence += 5
        elif rr >= 2.0:
            confidence += 4
        elif rr >= 1.5:
            confidence += 2
        
        return min(95, confidence)
    
    def calculate_verdict(self, rvol: float, confidence: int, opt_metrics: dict = None) -> str:
        """Calculate verdict based on execution parameters + options flow"""
        reasons = []

        if rvol < self.MIN_RVOL:
            reasons.append(f"Low volume ({rvol:.2f}x < {self.MIN_RVOL}x)")

        if confidence < self.MIN_CONFIDENCE:
            reasons.append(f"Low confidence ({confidence}% < {self.MIN_CONFIDENCE}%)")

        # Base equity verdict
        if not reasons:
            base_verdict = "✅ HIGH CONVICTION"
        elif len(reasons) == 1:
            base_verdict = f"⚠️ CAUTION - {reasons[0]}"
        else:
            base_verdict = f"❌ SKIP - {' + '.join(reasons)}"

        # Add options context if available
        if opt_metrics and base_verdict.startswith("✅"):
            pc = opt_metrics.get("pc_ratio", 1.0)
            vol_oi = opt_metrics.get("vol_oi_ratio", 1.0)
            iv = opt_metrics.get("avg_iv", 50.0)

            # Options alignment assessment
            if pc < 0.7 and vol_oi > 2.0:
                # Strong bullish + aggressive new positioning = institutional backing
                return base_verdict + " + Institutional bullish positioning"
            elif pc > 1.2 and vol_oi > 2.0:
                # Bearish + aggressive new positioning = institutional hedging
                return base_verdict + " ⚠️ But institutional puts active"
            elif iv > 80:
                # Very high IV = IV crush risk
                return base_verdict + " ⚠️ IV crush risk (very expensive)"
            elif iv < 30 and vol_oi > 1.5:
                # Cheap + unusual volume = good entry pricing
                return base_verdict + " ✓ Cheap pricing + active buying"

        return base_verdict

    @staticmethod
    def detect_macro_driver(symbol: str) -> str:
        """Detect macro driver for equities and futures"""
        # Precious metals & safe haven
        if symbol in ["GLD", "SLV", "TLT", "IEF", "/GC", "/ZB"]:
            return "Safe Haven Flow"

        # Broad market & tech futures
        elif symbol in ["/ES"]:
            return "Broad Market Signal"
        elif symbol in ["/NQ", "NVDA", "TSLA", "QQQ"]:
            return "Growth/Tech Momentum"

        # Energy & inflation
        elif symbol in ["/CL"]:
            return "Energy/Inflation Signal"

        # Crypto
        elif symbol in ["COIN"]:
            return "Crypto Institutional"

        # Default
        else:
            return "Breakout Pattern"
    
    def calculate_position_size(self, entry_price: float, stop_loss: float) -> int:
        """Calculate shares (simple: risk / entry)"""
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            return 0
        shares = int(self.risk_amount_per_trade / risk_per_share)
        
        # Cap at 5% of account
        max_position_cost = self.account_balance * 0.05
        if shares * entry_price > max_position_cost:
            shares = int(max_position_cost / entry_price)
        
        return shares
    
    def generate_alert(self, symbol: str, entry: float, stop_loss: float,
                      take_profit: float, rvol: float, rsi: float,
                      ema20: float, sma200: float) -> dict:
        """Generate alert with equity + options flow intelligence"""

        # Calculate shares
        shares = self.calculate_position_size(entry, stop_loss)

        # Risk/reward
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        rr = reward / risk if risk > 0 else 0

        # Confidence
        price_above_ema = entry > ema20
        price_above_sma = entry > sma200
        confidence = self.calculate_dynamic_confidence(rvol, rsi, price_above_ema, price_above_sma,
                                                       entry, stop_loss, take_profit)

        # Macro
        macro = self.detect_macro_driver(symbol)

        # Options flow metrics (alerts only - informational)
        opt_metrics = self.get_options_metrics(symbol)

        # Verdict assessment (with options context if available)
        verdict = self.calculate_verdict(rvol, confidence, opt_metrics)

        alert_dict = {
            "symbol": symbol,
            "entry": round(entry, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "shares": shares,
            "dollar_risk": round(risk * shares, 2),
            "dollar_reward": round(reward * shares, 2),
            "risk_reward": round(rr, 2),
            "confidence": confidence,
            "macro_driver": macro,
            "rsi": round(rsi, 1),
            "rvol": round(rvol, 2),
            "verdict": verdict
        }

        # Add options metrics if available
        if opt_metrics:
            alert_dict["options"] = opt_metrics

            # Add recommended options strategy (alerts only - for user reference)
            opt_strategy = self.select_options_strategy(
                entry_price=entry,
                target_price=take_profit,
                stop_price=stop_loss,
                iv=opt_metrics.get("avg_iv", 50.0),
                pc_ratio=opt_metrics.get("pc_ratio", 1.0),
                vol_oi=opt_metrics.get("vol_oi_ratio", 1.0)
            )
            alert_dict["opt_strategy"] = opt_strategy

        return alert_dict


# ============================================================================
# EXAMPLE
# ============================================================================

if __name__ == "__main__":
    engine = EnhancedAlertEngine(account_balance=50000, risk_pct_per_trade=1.0)
    
    # GLD
    gld = engine.generate_alert(
        symbol="GLD", entry=408.89, stop_loss=397.39, take_profit=431.89,
        rvol=2.14, rsi=54.2, ema20=405.00, sma200=400.00
    )
    
    # SLV
    slv = engine.generate_alert(
        symbol="SLV", entry=60.02, stop_loss=57.22, take_profit=65.63,
        rvol=2.07, rsi=51.9, ema20=58.50, sma200=55.00
    )
    
    print("="*70)
    print("🟡 GLD")
    print("="*70)
    print(f"Entry:         ${gld['entry']}")
    print(f"Stop Loss:     ${gld['stop_loss']}")
    print(f"Take Profit:   ${gld['take_profit']}")
    print()
    print(f"BUY:           {gld['shares']} shares")
    print(f"Risk:          ${gld['dollar_risk']:.2f}")
    print(f"Reward:        ${gld['dollar_reward']:.2f}")
    print(f"R/R:           {gld['risk_reward']}:1")
    print()
    print(f"Confidence:    {gld['confidence']}%")
    print(f"Driver:        {gld['macro_driver']}")
    
    print()
    print("="*70)
    print("🥈 SLV")
    print("="*70)
    print(f"Entry:         ${slv['entry']}")
    print(f"Stop Loss:     ${slv['stop_loss']}")
    print(f"Take Profit:   ${slv['take_profit']}")
    print()
    print(f"BUY:           {slv['shares']} shares")
    print(f"Risk:          ${slv['dollar_risk']:.2f}")
    print(f"Reward:        ${slv['dollar_reward']:.2f}")
    print(f"R/R:           {slv['risk_reward']}:1")
    print()
    print(f"Confidence:    {slv['confidence']}%")
    print(f"Driver:        {slv['macro_driver']}")
    print("="*70)

