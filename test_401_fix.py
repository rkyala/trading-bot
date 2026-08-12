#!/usr/bin/env python3
"""
Test script to verify 401 error handling and retry logic in get_open_symbols().

Tests:
1. ✅ Success case: Positions fetched correctly
2. ✅ Retry case: 401 on attempt 1, success on attempt 2
3. ✅ Halt case: 401 on both attempts (returns None)
4. ✅ Other error case: Non-401 HTTP error (returns None)
"""

import sys
import json
from unittest.mock import patch, MagicMock

# Mock setup
sys.path.insert(0, '.')

def test_401_fix():
    """Test the 401 error handling and retry logic."""

    print("=" * 70)
    print("Testing 401 Error Handling & Retry Logic")
    print("=" * 70)

    # Test 1: Successful fetch
    print("\n[TEST 1] Successful position fetch")
    print("-" * 70)

    with patch('bot.get_rh_access_token') as mock_token:
        with patch('bot.requests.get') as mock_get:
            mock_token.return_value = "fake_token"
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "results": [
                    {"symbol": "INTC", "quantity": "1.5"},
                    {"symbol": "AMAT", "quantity": "2.0"},
                ]
            }
            mock_get.return_value = mock_response

            from bot import get_open_symbols
            result = get_open_symbols()

            assert result == {"INTC", "AMAT"}, f"Expected {{'INTC', 'AMAT'}}, got {result}"
            print(f"✅ PASS: Returned positions: {result}")

    # Test 2: 401 on attempt 1, success on attempt 2
    print("\n[TEST 2] 401 on first attempt, success on retry")
    print("-" * 70)

    with patch('bot.get_rh_access_token') as mock_token:
        with patch('bot.requests.get') as mock_get:
            with patch('bot.time.sleep'):  # Skip actual sleep
                mock_token.return_value = "fake_token"

                # Create response objects for retry scenario
                mock_response_401 = MagicMock()
                mock_response_401.status_code = 401

                mock_response_200 = MagicMock()
                mock_response_200.status_code = 200
                mock_response_200.json.return_value = {
                    "results": [
                        {"symbol": "LRCX", "quantity": "1.0"},
                    ]
                }

                # First call returns 401, second call returns 200
                mock_get.side_effect = [mock_response_401, mock_response_200]

                from bot import get_open_symbols
                result = get_open_symbols()

                assert result == {"LRCX"}, f"Expected {{'LRCX'}}, got {result}"
                assert mock_get.call_count == 2, f"Expected 2 calls, got {mock_get.call_count}"
                print(f"✅ PASS: Retried and succeeded, returned positions: {result}")

    # Test 3: 401 on both attempts (should return None)
    print("\n[TEST 3] 401 on both attempts (should halt trading)")
    print("-" * 70)

    with patch('bot.get_rh_access_token') as mock_token:
        with patch('bot.requests.get') as mock_get:
            with patch('bot.time.sleep'):  # Skip actual sleep
                mock_token.return_value = "fake_token"

                mock_response_401 = MagicMock()
                mock_response_401.status_code = 401

                # Both calls return 401
                mock_get.side_effect = [mock_response_401, mock_response_401]

                from bot import get_open_symbols
                result = get_open_symbols()

                assert result is None, f"Expected None (halt signal), got {result}"
                print(f"✅ PASS: Both attempts failed with 401, returned None (HALT signal)")

    # Test 4: Other HTTP error (should return None)
    print("\n[TEST 4] Non-401 HTTP error (should halt trading)")
    print("-" * 70)

    with patch('bot.get_rh_access_token') as mock_token:
        with patch('bot.requests.get') as mock_get:
            mock_token.return_value = "fake_token"

            mock_response_error = MagicMock()
            mock_response_error.status_code = 403  # Forbidden (not 401)

            mock_get.return_value = mock_response_error

            from bot import get_open_symbols
            result = get_open_symbols()

            assert result is None, f"Expected None (halt signal), got {result}"
            print(f"✅ PASS: HTTP 403 error, returned None (HALT signal)")

    # Test 5: No token (should return None)
    print("\n[TEST 5] Cannot get token (should halt trading)")
    print("-" * 70)

    with patch('bot.get_rh_access_token') as mock_token:
        mock_token.return_value = None

        from bot import get_open_symbols
        result = get_open_symbols()

        assert result is None, f"Expected None (halt signal), got {result}"
        print(f"✅ PASS: Token unavailable, returned None (HALT signal)")

    # Test 6: Empty positions (valid case)
    print("\n[TEST 6] No open positions (valid empty result)")
    print("-" * 70)

    with patch('bot.get_rh_access_token') as mock_token:
        with patch('bot.requests.get') as mock_get:
            mock_token.return_value = "fake_token"

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"results": []}

            mock_get.return_value = mock_response

            from bot import get_open_symbols
            result = get_open_symbols()

            assert result == set(), f"Expected empty set, got {result}"
            print(f"✅ PASS: No positions owned, returned empty set (can trade)")

    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED")
    print("=" * 70)
    print("\nFix Summary:")
    print("  • 401 errors now retry once with fresh token")
    print("  • Auth failures return None (signal to halt trading)")
    print("  • Empty positions return empty set (can still trade)")
    print("  • 2 max retries + sleep between attempts")
    print("  • ERROR level logging for critical failures")
    print()

if __name__ == "__main__":
    test_401_fix()
