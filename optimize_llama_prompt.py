#!/usr/bin/env python3
"""
Llama Prompt Optimization
Test different prompting strategies to improve confidence calibration
"""

import json
from datetime import datetime
from local_llm_wrapper import LocalLLMWrapper

class LlamaPromptOptimizer:
    """Test and optimize Llama prompts"""

    def __init__(self):
        self.llm = LocalLLMWrapper()
        self.results = {}

    def test_prompts(self):
        """Test different prompt strategies"""

        test_cases = [
            {
                "symbol": "INTC",
                "pct_change": 2.3,
                "anomaly": 34.5,
                "technical": {
                    "rsi": 65,
                    "rsi_signal": "OVERBOUGHT",
                    "vwap": 90.50,
                    "vwap_signal": "BULLISH",
                    "trend": "UPTREND"
                }
            }
        ]

        prompt_strategies = [
            {
                "name": "Current (Balanced)",
                "description": "Current prompt with all context",
                "modifier": lambda p, t, c: p  # No change
            },
            {
                "name": "Aggressive (High Bar)",
                "description": "Require stronger signals for confidence",
                "modifier": lambda p, t, c: self._add_aggressive_modifier(p)
            },
            {
                "name": "Conservative (Safety First)",
                "description": "Emphasize risk and downside",
                "modifier": lambda p, t, c: self._add_conservative_modifier(p)
            },
            {
                "name": "Technical Heavy",
                "description": "Emphasize technical signals",
                "modifier": lambda p, t, c: self._add_technical_emphasis(p, t)
            },
            {
                "name": "Mean-Reversion Focus",
                "description": "Optimize for mean-reversion setups",
                "modifier": lambda p, t, c: self._add_mean_reversion_focus(p, t)
            }
        ]

        print("\n" + "="*80)
        print("LLAMA PROMPT OPTIMIZATION TEST")
        print("="*80 + "\n")

        for test_case in test_cases:
            symbol = test_case["symbol"]
            print(f"📊 Test Case: {symbol}")
            print(f"   Change: {test_case['pct_change']:+.1f}%")
            print(f"   Anomaly: {test_case['anomaly']:.1f}/100")
            print(f"   Technical: RSI {test_case['technical']['rsi']} (OVERBOUGHT), Uptrend\n")

            for strategy in prompt_strategies:
                print(f"   🔄 {strategy['name']}...")

                # Build base prompt
                base_prompt = self._build_base_prompt(test_case)

                # Apply strategy modifier
                modified_prompt = strategy["modifier"](base_prompt, test_case["technical"], test_case)

                # Test prompt
                try:
                    result = self.llm.analyze_trade(
                        symbol=symbol,
                        pct_change=test_case["pct_change"],
                        anomaly_score=test_case["anomaly"],
                        regime="range-bound"
                    )

                    confidence = result.get("confidence", 0)
                    self.results[strategy["name"]] = {
                        "confidence": confidence,
                        "reasoning": result.get("reason", "")[:100]
                    }

                    print(f"      Confidence: {confidence}%")
                    print(f"      Reasoning: {result.get('reason', '')[:80]}...\n")

                except Exception as e:
                    print(f"      Error: {e}\n")

        # Compare results
        self._compare_strategies()

    def _build_base_prompt(self, test_case):
        """Build base prompt for testing"""
        return f"""Analyze {test_case['symbol']} for mean-reversion trading.
Price change: {test_case['pct_change']:+.1f}%
Anomaly: {test_case['anomaly']:.0f}/100
Technical: RSI {test_case['technical']['rsi']} (OVERBOUGHT), Uptrend, Price > VWAP
Give confidence 0-100 for BUY RIGHT NOW."""

    def _add_aggressive_modifier(self, prompt):
        """Modify prompt to require stronger signals"""
        addition = """

IMPORTANT: Only high-conviction trades!
- RSI >70 must show clear trend reversal
- VWAP confirmation required
- Fibonacci or pivot support required
- Penalize trades with weak confluence
Range: 0-100, but expect <60% for most setups"""
        return prompt + addition

    def _add_conservative_modifier(self, prompt):
        """Modify prompt to emphasize downside risk"""
        addition = """

CRITICAL: Emphasize downside protection
- Consider the stop-loss placement
- What's the risk/reward ratio?
- Is there technical support nearby?
- Be conservative with overbought signals
Range: 0-100, but prioritize capital preservation"""
        return prompt + addition

    def _add_technical_emphasis(self, prompt, technical):
        """Emphasize technical signals"""
        addition = f"""

TECHNICAL SIGNALS ONLY:
- RSI Level: {technical['rsi']} ({technical['rsi_signal']})
- VWAP Signal: {technical['vwap_signal']}
- Trend: {technical['trend']}
- Confluence: {'High' if technical['rsi_signal'] in ['OVERBOUGHT', 'OVERSOLD'] else 'Medium'}

Score based on technical alignment only."""
        return prompt + addition

    def _add_mean_reversion_focus(self, prompt, technical):
        """Optimize for mean-reversion"""
        addition = f"""

MEAN-REVERSION SETUP:
Looking for: Overbought/oversold + trend confirmation
Current: RSI {technical['rsi']} + {technical['trend']}

Best case: {technical['rsi_signal']} in strong {technical['trend']}
= Pullback likely = Good entry

Give high confidence ONLY if:
1. RSI is clearly OVERBOUGHT/OVERSOLD
2. Trend is clearly established (up or down)
3. Support/resistance nearby

Score mean-reversion quality."""
        return prompt + addition

    def _compare_strategies(self):
        """Compare all strategy results"""

        print("\n" + "="*80)
        print("STRATEGY COMPARISON")
        print("="*80 + "\n")

        if not self.results:
            print("No results to compare")
            return

        print(f"{'Strategy':<25} {'Confidence':<15} {'Verdict':<20}")
        print("-" * 60)

        sorted_results = sorted(self.results.items(), key=lambda x: x[1]["confidence"], reverse=True)

        for strategy, data in sorted_results:
            conf = data["confidence"]
            if conf >= 70:
                verdict = "✅ BULLISH"
            elif conf >= 50:
                verdict = "⚠️ NEUTRAL"
            else:
                verdict = "❌ BEARISH"

            print(f"{strategy:<25} {conf:>3}%{'':<10} {verdict:<20}")

        # Recommendation
        best = sorted_results[0]
        print(f"\n🎯 RECOMMENDATION:")
        print(f"   Use '{best[0]}' strategy")
        print(f"   Produces most {'' if best[1]['confidence'] >= 60 else 'conservative'} confidence")

        # Save results
        with open("llama_prompt_optimization.json", "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "test_results": self.results,
                "best_strategy": best[0],
                "best_confidence": best[1]["confidence"]
            }, f, indent=2)

        print(f"\n💾 Results saved: llama_prompt_optimization.json")
        print("="*80 + "\n")


if __name__ == "__main__":
    print("\n🔬 Optimizing Llama prompts...")
    print("Testing different strategies to improve confidence calibration\n")

    optimizer = LlamaPromptOptimizer()
    optimizer.test_prompts()
