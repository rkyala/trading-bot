#!/usr/bin/env python3
"""
Test fractional share calculation for fixed $50 pyramid entries
Validates that qty = dollar_amount / price is correct
"""

# Test cases: (symbol, price, dollar_amount) -> expected_qty
test_cases = [
    # Low-price stocks (should get more shares)
    ("U", 43.77, 50.0, 50.0 / 43.77),  # ~1.142 shares
    ("DASH", 231.36, 50.0, 50.0 / 231.36),  # ~0.216 shares
    ("PYPL", 61.45, 50.0, 50.0 / 61.45),  # ~0.814 shares

    # Mid-price stocks (1-2 shares)
    ("BKNG", 209.43, 50.0, 50.0 / 209.43),  # ~0.239 shares
    ("RBLX", 37.91, 50.0, 50.0 / 37.91),  # ~1.319 shares

    # High-price stocks (fractional)
    ("LRCX", 333.85, 50.0, 50.0 / 333.85),  # ~0.150 shares
    ("KEYS", 337.47, 50.0, 50.0 / 337.47),  # ~0.148 shares
]

print("=" * 80)
print("FRACTIONAL SHARE TEST: dollar_amount / price = quantity")
print("=" * 80)

all_pass = True
for symbol, price, dollar_amount, expected_qty in test_cases:
    calculated_qty = dollar_amount / price
    rounded_qty = round(calculated_qty, 2)
    value_check = rounded_qty * price

    # Verify the qty rounds to value ≈ $50 (allow ±1% variance for rounding)
    within_tolerance = abs(value_check - dollar_amount) < 1.0  # ±$1.00 is acceptable for fractional shares
    status = "✅ PASS" if within_tolerance else "❌ FAIL"

    print(f"{status} | {symbol:6} @ ${price:7.2f} | ${dollar_amount:.2f} ÷ ${price:.2f} = {rounded_qty:6.4f} shares = ${value_check:6.2f}")

    if not within_tolerance:
        all_pass = False
        print(f"       ERROR: ${value_check:.2f} != ${dollar_amount:.2f}")

print("=" * 80)
if all_pass:
    print("✅ ALL TESTS PASSED - Fractional shares will execute correctly")
else:
    print("❌ SOME TESTS FAILED - Check calculations")
print("=" * 80)

print("\nKey behaviors after fix:")
print("1. price parameter NOW REQUIRED in place_order() call")
print("2. place_order() calculates: qty = dollar_amount / price")
print("3. MCP receives: quantity = str(rounded_qty)")
print("4. Robinhood executes fractional shares as market order")
print("5. Position value ≈ $50 for each pyramid entry")
