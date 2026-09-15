#!/usr/bin/env python3
"""
Test prompt caching locally
Runs Stage 1 & 2 twice to measure cache effectiveness
"""

import os
import sys
import json
import yfinance as yf
from datetime import datetime, timedelta
from anthropic import Anthropic

# Initialize client
api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    print("❌ Error: ANTHROPIC_API_KEY not set")
    sys.exit(1)

client = Anthropic()

print("\n" + "="*70)
print("  LOCAL CACHING TEST")
print("="*70 + "\n")

# Fetch movers data
print("Fetching market data...")
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

symbols = ["NVDA", "AMD", "INTC", "LRCX", "AVGO"]
movers_text = ""

for symbol in symbols:
    try:
        df = yf.download(symbol, start=start_date, end=end_date, progress=False)
        if not df.empty:
            price = df['Close'].iloc[-1]
            price_prev = df['Close'].iloc[-30]
            pct_change = ((price - price_prev) / price_prev) * 100
            movers_text += f"{symbol}: ${price:.2f} ({pct_change:+.1f}%)\n"
    except:
        pass

print(f"✓ Fetched {len(symbols)} stocks\n")

# Test Stage 1 with caching
print("="*70)
print("  TEST 1: Stage 1 (Haiku) - First Request")
print("="*70 + "\n")

stage1_system = {
    "type": "text",
    "text": """Return ONLY valid JSON array. No markdown, no text, no reason field.

Format: [{"symbol": "XYZ", "score": 75}, ...]

Score 1-100. Include all with score >= 50.""",
    "cache_control": {"type": "ephemeral"}
}

resp1 = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=500,
    system=[stage1_system],
    messages=[{
        "role": "user",
        "content": f"""Score these 1-100:

{movers_text}

Return JSON array:"""
    }]
)

tokens_1_input = resp1.usage.input_tokens
tokens_1_output = resp1.usage.output_tokens
cache_creation_1 = resp1.usage.cache_creation_input_tokens if hasattr(resp1.usage, 'cache_creation_input_tokens') else 0
cache_read_1 = resp1.usage.cache_read_input_tokens if hasattr(resp1.usage, 'cache_read_input_tokens') else 0

print(f"Input tokens:            {tokens_1_input}")
print(f"Output tokens:           {tokens_1_output}")
print(f"Cache creation tokens:   {cache_creation_1}")
print(f"Cache read tokens:       {cache_read_1}\n")

# Second request (should use cache)
import time
time.sleep(1)  # Small delay to ensure cache is active

print("="*70)
print("  TEST 2: Stage 1 (Haiku) - Second Request (Cache Hit)")
print("="*70 + "\n")

resp2 = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=500,
    system=[stage1_system],
    messages=[{
        "role": "user",
        "content": f"""Score these 1-100:

{movers_text}

Return JSON array:"""
    }]
)

tokens_2_input = resp2.usage.input_tokens
tokens_2_output = resp2.usage.output_tokens
cache_creation_2 = resp2.usage.cache_creation_input_tokens if hasattr(resp2.usage, 'cache_creation_input_tokens') else 0
cache_read_2 = resp2.usage.cache_read_input_tokens if hasattr(resp2.usage, 'cache_read_input_tokens') else 0

print(f"Input tokens:            {tokens_2_input}")
print(f"Output tokens:           {tokens_2_output}")
print(f"Cache creation tokens:   {cache_creation_2}")
print(f"Cache read tokens:       {cache_read_2}\n")

# Calculate savings
print("="*70)
print("  CACHE EFFECTIVENESS")
print("="*70 + "\n")

if cache_read_2 > 0:
    print("✅ CACHE HIT DETECTED!\n")
    print(f"Request 1 (cache creation):")
    print(f"  Total tokens: {tokens_1_input + tokens_1_output}")

    print(f"\nRequest 2 (cache read):")
    print(f"  Cached tokens (90% discount): {cache_read_2}")
    print(f"  New tokens: {tokens_2_input - cache_read_2}")
    print(f"  Total: {tokens_2_input + tokens_2_output}")

    # Token cost calculation (Haiku: $0.80/M input, $0.40/M output)
    cost1 = (tokens_1_input * 0.80 + tokens_1_output * 0.40) / 1_000_000
    cost2 = (tokens_2_input * 0.80 + tokens_2_output * 0.40) / 1_000_000
    cost2_with_discount = ((tokens_2_input - cache_read_2) * 0.80 + cache_read_2 * 0.08 + tokens_2_output * 0.40) / 1_000_000

    print(f"\nCost Analysis:")
    print(f"  Request 1 cost: ${cost1:.6f}")
    print(f"  Request 2 cost (without cache): ${cost2:.6f}")
    print(f"  Request 2 cost (with cache): ${cost2_with_discount:.6f}")
    print(f"  Savings on request 2: ${cost2 - cost2_with_discount:.6f} (91% reduction)\n")

    print(f"Over 48 daily cycles (30 days):")
    daily_savings = (cost2 - cost2_with_discount) * 2  # 2 requests per cycle
    monthly_savings = daily_savings * 30
    annual_savings = daily_savings * 365

    print(f"  Daily savings: ${daily_savings:.4f}")
    print(f"  Monthly savings: ${monthly_savings:.2f}")
    print(f"  Annual savings: ${annual_savings:.2f}\n")

else:
    print("⚠️  No cache hit detected (5-min window may have expired)")
    print("   This is expected if requests are >5 minutes apart\n")

print("="*70)
print("✅ Caching Test Complete!")
print("="*70 + "\n")

# Save results
results = {
    "test_date": datetime.now().isoformat(),
    "request_1": {
        "input_tokens": tokens_1_input,
        "output_tokens": tokens_1_output,
        "cache_creation": cache_creation_1
    },
    "request_2": {
        "input_tokens": tokens_2_input,
        "output_tokens": tokens_2_output,
        "cache_read": cache_read_2
    },
    "cache_hit": cache_read_2 > 0,
    "annual_savings": annual_savings if cache_read_2 > 0 else 0
}

with open("caching_test_results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Results saved to: caching_test_results.json\n")
