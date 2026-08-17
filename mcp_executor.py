#!/usr/bin/env python3
"""
MCP Executor Service (Option B: Hybrid Architecture)
Runs on Railway, receives trading decisions from Mac, executes via MCP

Mac sends: {"symbol": "INTC", "action": "BUY", "confidence": 81}
Railway executes: Places order on Robinhood via MCP
"""

import os
import sys
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__)

print("\n" + "="*70)
print("  MCP EXECUTOR SERVICE (Option B: Hybrid Architecture)")
print("="*70 + "\n")

# ============================================================================
# CONFIGURATION
# ============================================================================

# Railway environment
RAILWAY_PORT = int(os.getenv("PORT", 5000))
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT", "development")

# Robinhood OAuth
RH_ACCOUNT = os.getenv("ROBINHOOD_ACCOUNT", "432591949")
RH_CLIENT_ID = os.getenv("ROBINHOOD_CLIENT_ID")
RH_REFRESH_TOKEN = os.getenv("ROBINHOOD_REFRESH_TOKEN")

# MCP Configuration
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://agent.robinhood.com/mcp/trading")
MCP_ENABLED = RH_CLIENT_ID and RH_REFRESH_TOKEN

log.info(f"Environment: {RAILWAY_ENV}")
log.info(f"Port: {RAILWAY_PORT}")
log.info(f"MCP Enabled: {MCP_ENABLED}")

# ============================================================================
# MCP EXECUTION (using Anthropic SDK)
# ============================================================================

try:
    from anthropic import Anthropic
    client = Anthropic()
    log.info("✅ Anthropic SDK loaded")
except ImportError:
    log.warning("⚠️  Anthropic SDK not available (optional)")
    client = None


def execute_trade_via_mcp(decision):
    """
    Execute trade on Robinhood using MCP

    Input: {
        "symbol": "INTC",
        "action": "BUY",
        "confidence": 81,
        "quantity": 5
    }

    Returns: {
        "status": "success" | "error",
        "order_id": "...",
        "message": "..."
    }
    """

    if not MCP_ENABLED:
        log.warning("MCP not enabled, skipping trade execution")
        return {
            "status": "skipped",
            "message": "MCP credentials not configured"
        }

    if not client:
        log.error("Anthropic client not available")
        return {
            "status": "error",
            "message": "Anthropic client not available"
        }

    symbol = decision.get("symbol")
    action = decision.get("action", "BUY").upper()
    quantity = int(decision.get("quantity", 1))

    log.info(f"Executing trade: {action} {quantity}x {symbol}")

    try:
        # Use Anthropic client with MCP to place order
        response = client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"Place a {action} order for {quantity} shares of {symbol} on account {RH_ACCOUNT}. Use the place_equity_order tool."
            }],
            betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
            mcp_servers=[{
                "type": "url",
                "url": MCP_SERVER_URL,
                "name": "robinhood",
                "authorization_token": RH_REFRESH_TOKEN,
            }]
        )

        log.info(f"✅ MCP response received: {response}")

        # Extract order result from response
        order_id = "N/A"
        for block in response.content:
            if hasattr(block, 'text'):
                if "order" in block.text.lower():
                    order_id = extract_order_id(block.text)
                    break

        return {
            "status": "success",
            "order_id": order_id,
            "message": f"Executed {action} {quantity}x {symbol}",
            "symbol": symbol,
            "action": action,
            "quantity": quantity
        }

    except Exception as e:
        log.error(f"MCP execution error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
            "symbol": symbol
        }


def extract_order_id(response_text):
    """Extract order ID from MCP response"""
    # Simple extraction - look for order ID pattern
    if "order" in response_text.lower():
        # Try to find order ID in response
        import re
        match = re.search(r'order[_\s]?id[":=\s]+([a-zA-Z0-9\-]+)', response_text, re.IGNORECASE)
        if match:
            return match.group(1)
    return "UNKNOWN"


# ============================================================================
# HEALTH CHECK
# ============================================================================

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for Railway"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "mcp_enabled": MCP_ENABLED,
        "service": "MCP Executor (Option B)"
    }), 200


# ============================================================================
# MAIN ENDPOINT: RECEIVE DECISIONS FROM MAC & EXECUTE
# ============================================================================

@app.route('/execute_trades', methods=['POST'])
def execute_trades():
    """
    Receive trading decisions from Mac
    Execute trades via MCP on Robinhood

    Request body:
    {
        "decisions": [
            {"symbol": "INTC", "action": "BUY", "confidence": 81},
            {"symbol": "AMD", "action": "BUY", "confidence": 75}
        ]
    }

    Response:
    {
        "status": "success",
        "executed": 2,
        "results": [...]
    }
    """

    try:
        data = request.get_json()
        decisions = data.get("decisions", [])

        if not decisions:
            log.warning("No decisions received")
            return jsonify({
                "status": "error",
                "message": "No decisions in request"
            }), 400

        log.info(f"Received {len(decisions)} decision(s) from Mac")

        # Execute each trade
        results = []
        executed_count = 0

        for i, decision in enumerate(decisions):
            symbol = decision.get("symbol")
            action = decision.get("action")
            confidence = decision.get("confidence", 0)

            log.info(f"  [{i+1}/{len(decisions)}] {symbol} {action} (confidence: {confidence}%)")

            # Execute via MCP
            result = execute_trade_via_mcp(decision)
            results.append(result)

            if result.get("status") == "success":
                executed_count += 1

        response = {
            "status": "success",
            "received": len(decisions),
            "executed": executed_count,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

        log.info(f"✅ Executed {executed_count}/{len(decisions)} trades")

        return jsonify(response), 200

    except Exception as e:
        log.error(f"Error processing trades: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ============================================================================
# STATUS ENDPOINT
# ============================================================================

@app.route('/status', methods=['GET'])
def status():
    """Get current executor status"""
    return jsonify({
        "service": "MCP Executor (Option B: Hybrid Architecture)",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "environment": RAILWAY_ENV,
        "mcp_enabled": MCP_ENABLED,
        "port": RAILWAY_PORT
    }), 200


# ============================================================================
# INFO ENDPOINT
# ============================================================================

@app.route('/info', methods=['GET'])
def info():
    """Get executor info"""
    return jsonify({
        "service": "MCP Executor",
        "version": "0.1.0",
        "architecture": "Option B: Hybrid",
        "description": "Receives trading decisions from Mac, executes via MCP on Railway",
        "endpoints": {
            "/health": "Health check",
            "/status": "Current status",
            "/execute_trades": "Execute trades (POST)",
            "/info": "This info"
        }
    }), 200


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404


@app.errorhandler(500)
def server_error(error):
    log.error(f"Server error: {error}")
    return jsonify({"status": "error", "message": "Internal server error"}), 500


# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    log.info("\n" + "="*70)
    log.info("  STARTING MCP EXECUTOR SERVICE")
    log.info("="*70)
    log.info(f"Environment: {RAILWAY_ENV}")
    log.info(f"Port: {RAILWAY_PORT}")
    log.info(f"MCP Enabled: {MCP_ENABLED}")
    log.info("\nEndpoints:")
    log.info("  GET  /health         - Health check")
    log.info("  GET  /status         - Status")
    log.info("  POST /execute_trades - Execute trades from Mac")
    log.info("  GET  /info           - Service info")
    log.info("\n" + "="*70 + "\n")

    # Start Flask server
    app.run(
        host="0.0.0.0",
        port=RAILWAY_PORT,
        debug=(RAILWAY_ENV == "development")
    )
