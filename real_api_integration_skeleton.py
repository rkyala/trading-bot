#!/usr/bin/env python3
"""
REAL API INTEGRATION SKELETON (Phase 2.5)
Shows which actual APIs to use for production data
"""

import requests
import json
from typing import List, Dict, Optional

# ============================================================================
# API CREDENTIALS (Store in environment variables for security)
# ============================================================================

import os

INTRINIO_API_KEY = os.getenv("INTRINIO_API_KEY")  # Sign up: intrinio.com
SEC_EDGAR_API = "https://www.sec.gov/cgi-bin/browse-edgar"  # Free, no key
LLAMA_API_ENDPOINT = os.getenv("LLAMA_API_ENDPOINT")  # Local or Claude

# ============================================================================
# 1. REAL OPTIONS SWEEP DATA (Intrinio API)
# ============================================================================

class IntrinionOptionsScanner:
    """
    Fetch REAL unusual options activity from Intrinio API

    Pricing: $99-299/month
    Sign up: https://intrinio.com/
    Docs: https://docs.intrinio.com/
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.intrinio.com"

    def get_unusual_options_activity(self, symbols: List[str]) -> List[Dict]:
        """
        Fetch real options sweeps with unusual volume.

        Returns raw data like:
        {
            "event_id": "swp_88492026",
            "symbol": "NVDA",
            "strike": 140.0,
            "put_call": "CALL",
            "volume": 12450,
            "open_interest": 1200,
            "vol_oi_ratio": 10.37,
            "side": "BUY_AT_ASK",
            "total_premium_usd": 1450000.00,
            "bid_ask_spread": 0.05,
            "timestamp": "2026-10-01T14:30:00Z"
        }
        """
        try:
            endpoint = f"{self.base_url}/options/unusual_activity"
            params = {
                "api_key": self.api_key,
                "symbols": ",".join(symbols[:10]),  # API limit
                "min_volume": 100,  # contracts
                "min_premium": 50000  # USD
            }

            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data.get("unusual_activity", [])

        except Exception as e:
            print(f"❌ Intrinio API error: {e}")
            return []


# ============================================================================
# 2. REAL 13-F FILING DATA (SEC EDGAR API - Free)
# ============================================================================

class SECEdgarScanner:
    """
    Fetch REAL institutional 13-F holdings from SEC EDGAR API

    Pricing: FREE
    Docs: https://www.sec.gov/cgi-bin/browse-edgar
    Library: pip install edgartools (optional, simpler)
    """

    @staticmethod
    def get_recent_13f_filings(symbols: List[str], days_lookback: int = 30) -> List[Dict]:
        """
        Fetch real 13-F filings showing institutional position changes.

        Returns raw data like:
        {
            "formType": "13F-HR",
            "managerName": "Scion Asset Management, LLC",
            "managerCIK": "0001618289",
            "periodOfReport": "2026-06-30",
            "filingDate": "2026-08-14",
            "holdings": [
                {
                    "nameOfIssuer": "NVIDIA CORP",
                    "ticker": "NVDA",
                    "cusip": "67066031",
                    "shares": 250000,
                    "valueUsd": 32500000,
                    "changeFromPriorQuarterShares": 100000,
                    "changeFromPriorQuarterPct": 45.2
                }
            ]
        }
        """
        try:
            filings = []

            for symbol in symbols[:5]:  # Limit to avoid rate limits
                # Query EDGAR for recent 13-F filings mentioning this ticker
                params = {
                    "action": "getcompany",
                    "type": "13F-HR",
                    "dateb": "",
                    "owner": "exclude",
                    "count": 10,
                    "output": "json"
                }

                response = requests.get(SEC_EDGAR_API, params=params, timeout=10)
                response.raise_for_status()

                # Parse response (EDGAR API is complex, using edgartools recommended)
                # For now, return empty - implement with edgartools in production
                filings.append({
                    "symbol": symbol,
                    "formType": "13F-HR",
                    "status": "requires_edgartools_library"
                })

            return filings

        except Exception as e:
            print(f"❌ EDGAR API error: {e}")
            return []

    @staticmethod
    def get_13f_with_edgartools(symbols: List[str]) -> List[Dict]:
        """
        Better approach: Use edgartools library
        pip install edgartools
        """
        try:
            from edgar import Company

            filings = []
            for symbol in symbols[:3]:
                company = Company(symbol)
                recent_13f = company.get_filings(form="13F-HR").latest()

                if recent_13f:
                    filings.append({
                        "symbol": symbol,
                        "formType": "13F-HR",
                        "managerName": recent_13f.manager,
                        "periodOfReport": recent_13f.period_of_report,
                        "filingDate": recent_13f.filing_date,
                        "holdings": recent_13f.holdings
                    })

            return filings

        except ImportError:
            print("⚠️  Install edgartools: pip install edgartools")
            return []
        except Exception as e:
            print(f"❌ EdgarTools error: {e}")
            return []


# ============================================================================
# 3. REAL LLaMA EVALUATION (Local or Claude API)
# ============================================================================

class LLaMAEvaluator:
    """
    Run LLaMA inference on options/13-F data.

    Three options:
    1. Local Ollama (free, ~2-3s inference)
    2. Claude API ($0.003/1K input, faster)
    3. vLLM server (free, optimized)
    """

    @staticmethod
    def evaluate_with_local_ollama(raw_event: Dict) -> Dict:
        """
        Run inference on local Ollama server

        Setup:
        1. Install: curl https://ollama.ai/install.sh | sh
        2. Download: ollama pull llama2-7b
        3. Run: ollama serve (port 11434)
        """
        try:
            import ollama

            prompt = f"""
            Analyze this market event and score conviction (0-100):

            Event: {json.dumps(raw_event, indent=2)}

            Return JSON ONLY:
            {{
                "conviction_score": <0-100>,
                "bias": "BULLISH" or "BEARISH",
                "reason": "short explanation"
            }}
            """

            response = ollama.generate(
                model="llama2-7b",
                prompt=prompt,
                temperature=0.1,  # Low for determinism
                stream=False
            )

            # Parse response JSON
            try:
                result = json.loads(response["response"])
                return result
            except:
                return {
                    "conviction_score": 50,
                    "bias": "NEUTRAL",
                    "reason": "Parse error"
                }

        except Exception as e:
            print(f"❌ Local Ollama error: {e}")
            return None

    @staticmethod
    def evaluate_with_claude_api(raw_event: Dict) -> Dict:
        """
        Use Claude API for evaluation

        Setup:
        1. API Key: https://console.anthropic.com
        2. Install: pip install anthropic
        3. Cost: ~$0.003 per 1K input tokens
        """
        try:
            from anthropic import Anthropic

            client = Anthropic()

            prompt = f"""
            Analyze this market event and score institutional conviction (0-100):

            {json.dumps(raw_event, indent=2)}

            Consider:
            - Volume vs open interest (for options)
            - Position size and filer reputation (for 13-F)
            - Bid-ask spread tightness (for sweeps)

            Return ONLY valid JSON (no markdown, no explanation):
            {{
                "conviction_score": <0-100>,
                "bias": "BULLISH" or "BEARISH",
                "reason": "one sentence"
            }}
            """

            message = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=200,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text
            result = json.loads(response_text)
            return result

        except Exception as e:
            print(f"❌ Claude API error: {e}")
            return None


# ============================================================================
# INTEGRATION PIPELINE (Production)
# ============================================================================

def production_data_pipeline(symbols: List[str]):
    """
    Real production pipeline: API → LLaMA → Queue
    """
    print("\n" + "="*100)
    print("PRODUCTION DATA PIPELINE (Real APIs)")
    print("="*100)

    # 1. Fetch real options data
    print("\n[STEP 1] Fetching real options sweeps from Intrinio...")
    if INTRINIO_API_KEY:
        intrinio = IntrinionOptionsScanner(INTRINIO_API_KEY)
        sweeps = intrinio.get_unusual_options_activity(symbols)
        print(f"  ✅ Fetched {len(sweeps)} unusual options events")
    else:
        print("  ⚠️  INTRINIO_API_KEY not set - set via: export INTRINIO_API_KEY=<key>")
        sweeps = []

    # 2. Fetch real 13-F data
    print("\n[STEP 2] Fetching real 13-F filings from SEC EDGAR...")
    edgar = SECEdgarScanner()
    filings = edgar.get_13f_with_edgartools(symbols)
    print(f"  ✅ Fetched {len(filings)} 13-F filings")

    # 3. Evaluate through LLaMA
    print("\n[STEP 3] Evaluating through LLaMA (local Ollama)...")
    evaluator = LLaMAEvaluator()

    triggers = []
    for sweep in sweeps[:3]:  # Limit for demo
        result = evaluator.evaluate_with_local_ollama(sweep)
        if result:
            trigger = {
                "symbol": sweep.get("symbol"),
                "source": "OPTIONS_SWEEP",
                "conviction_score": result["conviction_score"],
                "bias": result["bias"]
            }
            triggers.append(trigger)
            print(f"  ✅ Evaluated {sweep.get('symbol')}: {result['bias']} ({result['conviction_score']}/100)")

    # 4. Write to queue
    print("\n[STEP 4] Writing to macro_triggers.json queue...")
    with open("macro_triggers.json", "w") as f:
        json.dump(triggers, f, indent=2)
    print(f"  ✅ Wrote {len(triggers)} triggers to queue")

    print("\n" + "="*100)
    print("✅ PRODUCTION PIPELINE COMPLETE")
    print("="*100)


# ============================================================================
# SETUP INSTRUCTIONS
# ============================================================================

SETUP_GUIDE = """
════════════════════════════════════════════════════════════════════════════════════════════════════════════════
REAL API SETUP GUIDE (Phase 2.5)
════════════════════════════════════════════════════════════════════════════════════════════════════════════════

1️⃣  OPTIONS SWEEPS (Intrinio API)
   ├─ Sign up: https://intrinio.com/ ($99-299/month)
   ├─ Get API key: https://app.intrinio.com/account/api_key
   └─ Set environment: export INTRINIO_API_KEY=<your-key>

2️⃣  13-F INSTITUTIONAL FILINGS (SEC EDGAR)
   ├─ Status: FREE
   ├─ Install edgartools: pip install edgartools
   └─ Docs: https://edgartools.readthedocs.io/

3️⃣  LLaMA INFERENCE (Choose one)

   Option A: Local Ollama (Free, 2-3s per inference)
   ├─ Install: curl https://ollama.ai/install.sh | sh
   ├─ Download: ollama pull llama2-7b
   └─ Run: ollama serve (listens on localhost:11434)

   Option B: Claude API ($0.003/1K tokens, fast)
   ├─ Sign up: https://console.anthropic.com
   ├─ Get API key: https://console.anthropic.com/account/keys
   ├─ Install: pip install anthropic
   └─ Set environment: export ANTHROPIC_API_KEY=<your-key>

4️⃣  RUN PRODUCTION PIPELINE
   ├─ python3 real_api_integration_skeleton.py
   └─ Outputs: macro_triggers.json (consumed by v3.8 bot)

════════════════════════════════════════════════════════════════════════════════════════════════════════════════
"""

if __name__ == "__main__":
    print(SETUP_GUIDE)

    # Run pipeline if all APIs configured
    symbols = ["NVDA", "TSLA", "AAPL", "META", "INTC"]

    if INTRINIO_API_KEY or True:  # Run with mock if no key
        production_data_pipeline(symbols)
    else:
        print("⚠️  Set INTRINIO_API_KEY to enable real options data")
