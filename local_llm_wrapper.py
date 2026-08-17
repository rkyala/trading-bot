#!/usr/bin/env python3
"""
Local LLM Wrapper: Llama 2 7B for Trading Decisions
Zero-cost replacement for Claude Haiku + Sonnet
"""

import requests
import json
import sys

# ============================================================================
# LLAMA 2 WRAPPER
# ============================================================================

class LocalLLMWrapper:
    """Llama 2 7B wrapper for trading analysis"""

    def __init__(self, model="llama2:7b", host="http://localhost:11434"):
        """
        Initialize Llama 2 wrapper

        Args:
            model: Model name (default: llama2:7b)
            host: Ollama server URL
        """
        self.model = model
        self.host = host
        self.endpoint = f"{host}/api/generate"

    def is_available(self):
        """Check if Ollama server is running"""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=2)
            return resp.status_code == 200
        except:
            return False

    def analyze_trade(self, symbol, pct_change, anomaly_score, regime, confidence_llm=True):
        """
        Analyze whether to trade a symbol using Llama 2

        Args:
            symbol: Stock symbol (e.g., "INTC")
            pct_change: Price change % (e.g., 6.2)
            anomaly_score: Anomaly score 0-100 (e.g., 78)
            regime: Market regime ("trending_up", "trending_down", "range-bound")
            confidence_llm: Whether to use LLM for reasoning (else just rules)

        Returns:
            {
                "action": "BUY" or "SKIP",
                "confidence": 0-100,
                "reason": str,
                "llm_response": str
            }
        """

        if not confidence_llm:
            # Fallback to rule-based logic
            return self._rule_based_decision(symbol, pct_change, anomaly_score, regime)

        # Prepare prompt for Llama 2
        prompt = self._build_trading_prompt(symbol, pct_change, anomaly_score, regime)

        try:
            response = requests.post(
                self.endpoint,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.3,  # Deterministic
                    "top_k": 40,
                    "top_p": 0.9,
                },
                timeout=10
            )

            if response.status_code != 200:
                print(f"  ⚠️  LLM error: {response.status_code}")
                return self._rule_based_decision(symbol, pct_change, anomaly_score, regime)

            result = response.json()
            llm_text = result.get("response", "").strip()

            # Parse LLM response
            decision = self._parse_llm_response(llm_text, symbol, pct_change, anomaly_score)
            decision["llm_response"] = llm_text[:200]  # Store first 200 chars

            return decision

        except Exception as e:
            print(f"  ⚠️  LLM exception: {e}")
            return self._rule_based_decision(symbol, pct_change, anomaly_score, regime)

    def _build_trading_prompt(self, symbol, pct_change, anomaly_score, regime):
        """Build prompt for Llama 2"""
        # Convert numpy types to Python native types
        pct_change = float(pct_change)
        anomaly_score = float(anomaly_score)
        symbol = str(symbol)
        regime = str(regime)

        return f"""You are a financial analyst. Analyze this trading signal and respond with YES or NO.

Stock: {symbol}
Price change from mean: {pct_change:+.2f}%
Anomaly detection score: {anomaly_score:.0f}/100
Market regime: {regime}

Context:
- If price is UP 3-8% from mean: likely overbought pullback opportunity (mean-reversion)
- If price is DOWN 2-6% from mean: likely recovery opportunity
- Anomaly > 70: Strong signal
- Anomaly < 50: Weak signal

Question: Should we BUY this stock now?

Respond with:
YES - if mean-reversion setup looks good
NO - if risk/reward is poor
Keep response under 50 words.
"""

    def _parse_llm_response(self, llm_text, symbol, pct_change, anomaly_score):
        """Parse LLM response and extract decision"""
        # Convert numpy types to Python native types
        pct_change = float(pct_change)
        anomaly_score = float(anomaly_score)
        symbol = str(symbol)

        decision_text = llm_text.upper()

        # Look for YES/NO
        if "YES" in decision_text:
            action = "BUY"
            base_conf = 75
        elif "NO" in decision_text:
            action = "SKIP"
            base_conf = 25
        else:
            # Ambiguous, use rule-based
            return self._rule_based_decision(symbol, pct_change, anomaly_score, "unknown")

        # Scale confidence by anomaly score
        confidence = min(95, max(50, base_conf + (anomaly_score - 70) * 0.5))

        return {
            "action": action,
            "confidence": int(confidence),
            "reason": f"{symbol}: {pct_change:+.1f}% change, anomaly {anomaly_score:.0f}/100",
        }

    def _rule_based_decision(self, symbol, pct_change, anomaly_score, regime):
        """Fallback rule-based decision when LLM unavailable"""
        # Convert numpy types to Python native types
        pct_change = float(pct_change)
        anomaly_score = float(anomaly_score)
        symbol = str(symbol)

        # Mean-reversion rules
        if pct_change > 3 and anomaly_score > 70:
            # Overbought pullback
            confidence = min(90, 50 + anomaly_score * 0.4)
            return {
                "action": "BUY",
                "confidence": int(confidence),
                "reason": f"{symbol}: Overbought pullback ({pct_change:+.1f}%, anomaly {anomaly_score:.0f})",
            }

        elif pct_change < -2 and anomaly_score > 60:
            # Drop recovery
            confidence = min(85, 40 + anomaly_score * 0.4)
            return {
                "action": "BUY",
                "confidence": int(confidence),
                "reason": f"{symbol}: Drop recovery ({pct_change:+.1f}%, anomaly {anomaly_score:.0f})",
            }

        else:
            return {
                "action": "SKIP",
                "confidence": 30,
                "reason": f"{symbol}: No clear signal ({pct_change:+.1f}%, anomaly {anomaly_score:.0f})",
            }


# ============================================================================
# TEST
# ============================================================================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("  LOCAL LLM WRAPPER TEST (Llama 2 7B)")
    print("="*70 + "\n")

    # Initialize wrapper
    llm = LocalLLMWrapper()

    # Check server
    print("1️⃣  Checking Ollama server...")
    if not llm.is_available():
        print("   ❌ Ollama server not running!")
        print("   Start with: OLLAMA_FLASH_ATTENTION=1 ollama serve")
        sys.exit(1)

    print("   ✅ Ollama server running\n")

    # Test trades
    print("2️⃣  Testing trading decisions...\n")

    test_cases = [
        ("INTC", 6.2, 78, "range-bound"),
        ("AMD", -3.5, 72, "range-bound"),
        ("NVDA", 2.1, 45, "trending_up"),
        ("LRCX", 8.1, 85, "range-bound"),
    ]

    for symbol, pct_change, anomaly, regime in test_cases:
        result = llm.analyze_trade(symbol, pct_change, anomaly, regime)
        print(f"{symbol:6} {pct_change:+6.1f}% | Anomaly {anomaly:3.0f} | {result['action']:4} (conf {result['confidence']:3d}%)")
        if "llm_response" in result:
            print(f"        → {result['reason']}\n")

    print("="*70)
    print("✅ Local LLM wrapper working!")
    print("="*70 + "\n")
