#!/usr/bin/env python3
"""
Debug: Check Robinhood Response Structure
"""

import json
import logging
from bot_production_final import LocalMCPClient, ConfigLoader

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

print('='*80)
print('DEBUG: ROBINHOOD RESPONSE STRUCTURE')
print('='*80)

config = ConfigLoader.load()
mcp = LocalMCPClient(config)

logger.info("\nFetching raw positions response...")
response = mcp.get_positions()

print("\n" + "="*80)
print("RAW RESPONSE")
print("="*80)
print(json.dumps(response, indent=2)[:2000])  # First 2000 chars

# Parse and display
if "result" in response and "content" in response["result"]:
    content_text = response["result"]["content"][0].get("text", "")
    if content_text:
        parsed = json.loads(content_text)
        print("\n" + "="*80)
        print("PARSED CONTENT")
        print("="*80)
        print(json.dumps(parsed, indent=2)[:2000])

        # Check structure
        print("\n" + "="*80)
        print("STRUCTURE ANALYSIS")
        print("="*80)
        if "data" in parsed:
            data = parsed["data"]
            print(f"Type of data: {type(data)}")

            if isinstance(data, list) and len(data) > 0:
                print(f"\nFirst position keys: {list(data[0].keys())}")
                print(f"First position: {json.dumps(data[0], indent=2)[:500]}")

mcp.stop()
