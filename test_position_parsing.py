#!/usr/bin/env python3
"""
Test position parsing logic with mock MCP responses
"""

import json
from unittest.mock import Mock

def test_parse_positions(response_format, description):
    """Test parsing with different response formats"""
    print(f"\n{'='*70}")
    print(f"TEST: {description}")
    print(f"{'='*70}")

    # Mock MCP response
    resp = Mock()
    resp.content = []

    if response_format == "empty_results":
        # Empty results - what we're currently getting
        resp.content = [
            Mock(type="text", text="I'll fetch the positions for you."),
            Mock(type="mcp_tool_result", text=json.dumps({
                "data": {
                    "results": []
                }
            })),
            Mock(type="text", text="No open positions found.")
        ]

    elif response_format == "with_positions":
        # Expected format with positions
        resp.content = [
            Mock(type="text", text="Fetching positions..."),
            Mock(type="mcp_tool_result", text=json.dumps({
                "data": {
                    "results": [
                        {"symbol": "GQQ", "quantity": "0.118301"},
                        {"symbol": "INTC", "quantity": "8.79"},
                        {"symbol": "LRCX", "quantity": "4.60"},
                        {"symbol": "AMAT", "quantity": "2.43"}
                    ]
                }
            })),
            Mock(type="text", text="Found 4 positions.")
        ]

    elif response_format == "nested_instrument":
        # Alternative format with instrument nesting
        resp.content = [
            Mock(type="mcp_tool_result", text=json.dumps({
                "data": {
                    "results": [
                        {
                            "symbol": "INTC",
                            "quantity": "8.79",
                            "instrument": {"symbol": "INTC"}
                        }
                    ]
                }
            }))
        ]

    elif response_format == "array_format":
        # Flat array instead of nested
        resp.content = [
            Mock(type="mcp_tool_result", text=json.dumps([
                {"symbol": "INTC", "quantity": "8.79"},
                {"symbol": "LRCX", "quantity": "4.60"}
            ]))
        ]

    # Parse using current logic
    owned_symbols = set()
    for block in resp.content:
        if hasattr(block, 'type') and block.type == "mcp_tool_result":
            try:
                result_text = block.text if hasattr(block, 'text') else str(block)
                if isinstance(result_text, str) and result_text.startswith('{'):
                    result_json = json.loads(result_text)
                    positions = result_json.get("data", {}).get("results", [])

                    for pos in positions:
                        symbol = pos.get("symbol", "").upper()
                        qty = float(pos.get("quantity", 0))
                        if symbol and qty > 0:
                            owned_symbols.add(symbol)
            except Exception as e:
                print(f"Parse error: {e}")

    print(f"Parsed symbols: {sorted(owned_symbols) if owned_symbols else 'EMPTY'}")
    if not owned_symbols:
        print("❌ PROBLEM: Expected positions but got empty result")
    else:
        print(f"✅ SUCCESS: Found {len(owned_symbols)} positions")

if __name__ == "__main__":
    print("\n🧪 Testing Position Parsing Logic")

    test_parse_positions("empty_results", "Empty Results (current problem)")
    test_parse_positions("with_positions", "With Real Positions (expected)")
    test_parse_positions("nested_instrument", "Nested Instrument Format")
    test_parse_positions("array_format", "Array Format (flat)")

    print(f"\n{'='*70}")
    print("DIAGNOSIS")
    print(f"{'='*70}")
    print("""
Current Findings:
- Parser works correctly with "data.results" format
- Empty results suggest MCP server returns no positions
- Possible causes:
  1. Account has no positions (but user screenshot shows otherwise)
  2. MCP returns different format than expected
  3. Claude isn't actually calling the tool (just returning text)
  4. Wrong account number or permissions issue

Next Step:
- Check Railway logs for new debug output
- Enhanced logging shows MCP response blocks
- Will reveal exact format MCP is using
""")
