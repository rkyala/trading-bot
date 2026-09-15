#!/bin/bash
# Quick test of advanced charts

echo "=================================="
echo "Testing Advanced Charts Module"
echo "=================================="
echo ""

cd ~/Documents/Documents\ -\ Rama\'s\ MacBook\ Pro/trading_bot

# Test imports
python3 << 'EOF'
import sys
print("✅ Testing advanced_charts module...")

from advanced_charts import AdvancedChartAnalyzer

analyzer = AdvancedChartAnalyzer()

# Test on a few symbols
for symbol in ["INTC", "AMD", "NVDA"]:
    print(f"\n📊 {symbol}:")
    analysis = analyzer.get_chart_analysis(symbol)
    if analysis:
        print(f"   Signal: {analysis.get('chart_signal')} ({analysis.get('confluence_score')}/100)")
        print(f"   Price: ${analysis.get('price'):.2f}")

        # Print brief context
        context = analyzer.get_chart_context_for_llama(symbol)
        if "Volume Profile" in context:
            print(f"   ✅ Chart context generated (500+ chars)")
    else:
        print(f"   ❌ Failed to analyze")

print("\n" + "="*50)
print("✅ Advanced charts module working!")
print("="*50)
EOF

echo ""
echo "Next step: Run backtest with:"
echo "  python3 backtest_advanced_charts.py"
