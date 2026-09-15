#!/usr/bin/env python3
"""Debug v2 to find why it's not generating trades"""

import sys
import logging
from datetime import datetime

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

print("\n" + "="*80)
print("DEBUG: Bot v2 Issue")
print("="*80 + "\n")

# Test 1: Import advanced_charts
print("✅ Test 1: Importing advanced_charts...")
try:
    from advanced_charts import AdvancedChartAnalyzer
    print("   ✅ Import successful")
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    sys.exit(1)

# Test 2: Instantiate analyzer
print("\n✅ Test 2: Creating AdvancedChartAnalyzer...")
try:
    analyzer = AdvancedChartAnalyzer()
    print("   ✅ Instantiation successful")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    sys.exit(1)

# Test 3: Analyze one symbol
print("\n✅ Test 3: Analyzing INTC...")
try:
    analysis = analyzer.get_chart_analysis("INTC")
    if analysis:
        print(f"   ✅ Analysis successful")
        print(f"      Price: ${analysis.get('price'):.2f}")
        print(f"      Signal: {analysis.get('chart_signal')}")
        print(f"      Confidence: {analysis.get('confluence_score')}/100")
    else:
        print(f"   ⚠️ Analysis returned None")
except Exception as e:
    print(f"   ❌ Failed: {e}")
    import traceback
    traceback.print_exc()

# Test 4: Get chart context
print("\n✅ Test 4: Getting chart context for Llama...")
try:
    context = analyzer.get_chart_context_for_llama("INTC")
    if context:
        print(f"   ✅ Context generated ({len(context)} chars)")
        print(f"   First 200 chars: {context[:200]}")
    else:
        print(f"   ⚠️ Context is empty")
except Exception as e:
    print(f"   ❌ Failed: {e}")

# Test 5: Test v2 bot import
print("\n✅ Test 5: Importing bot_dry_run_v2...")
try:
    from bot_dry_run_v2 import DryRunBotV2
    print("   ✅ Import successful")
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: Run one cycle
print("\n✅ Test 6: Running one v2 cycle...")
try:
    bot = DryRunBotV2()
    print(f"   Bot initialized")
    print(f"   - Llama: {'✅' if bot.llm else '❌'}")
    print(f"   - Charts: {'✅' if bot.chart else '❌'}")
    print(f"   - FinRL: {'✅' if bot.learner else '❌'}")

    bot.run_cycle()
    print(f"\n   ✅ Cycle completed")
    print(f"   Trades generated: {len(bot.trades)}")
    for trade in bot.trades:
        print(f"      - {trade['symbol']}: {trade['confidence']}% -> +${trade['profit']:.2f}")

except Exception as e:
    print(f"   ❌ Cycle failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("DEBUG COMPLETE")
print("="*80 + "\n")
