# MCP Integration Guide: Week 2 Migration Plan

**Status**: Mock mode active (Tue-Fri). Real MCP wiring planned for Week 2.

---

## Current State (Tuesday 9/8 - Friday 9/11)

### Mock Mode (uw_robinhood_mcp.py)
```python
client = RobinhoodMCPClient(use_mock=True)  # ← Default for dry-run

# Returns deterministic responses:
order = await client.place_option_order(...)
→ OrderResponse(success=True, order_id="mock-order-00127", message="...")

quotes = await client.get_index_quotes(["SPX"])
→ [{"symbol": "SPX", "last_price": 4500.15, ...}]
```

**Why mock for Tue-Fri**:
- ✅ No Robinhood OAuth needed
- ✅ Deterministic (repeatable tests)
- ✅ 14/14 tests pass
- ✅ Safe (no accidental real orders)
- ✅ Validates architecture before real money

---

## Week 2 Migration (Sep 15-19)

### Step 1: Extract Real MCP from bot.py

**Location**: `bot.py:1233-1380` (stage3_execute function)

**Key Components**:

```python
# 1. MCP Server Configuration (LOCKED - do not change)
mcp_servers=[{
    "type": "url",
    "url": "https://agent.robinhood.com/mcp/trading",  # Production endpoint
    "name": "robinhood",                                 # Registry name
    "authorization_token": rh_token,                    # OAuth token
}]

# 2. Claude Beta API Call
resp = client.beta.messages.create(
    model="claude-opus-4-8",
    max_tokens=2000,
    system=[{
        "type": "text",
        "text": "You are a trading execution system...",
        "cache_control": {"type": "ephemeral"}
    }],
    messages=messages,
    betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
    mcp_servers=[...]
)

# 3. Tool Use Loop - Process MCP Responses
for block in resp.content:
    if block.type in ("tool_use", "mcp_tool_use"):
        tool_name = block.name
        tool_input = block.input
        # Handle tool execution results
```

### Step 2: Create Real MCP Executor

**New file**: `uw_robinhood_mcp_real.py`

```python
"""
Real Robinhood MCP Executor (Week 2)
Mirrors bot.py stage3_execute but simplified for unusual_whales_bot
"""

from anthropic import Anthropic
import os
import json

class RobinhoodMCPExecutor:
    """Real MCP integration using Claude beta API"""
    
    def __init__(self, client):
        self.client = client  # Anthropic client
        self.mcp_url = "https://agent.robinhood.com/mcp/trading"
        self.mcp_name = "robinhood"
        
    async def get_positions(self) -> List[Dict]:
        """Fetch current positions (fresh, no cache - prevent duplicates)"""
        instruction = """Call get_equity_positions to fetch all current holdings.
        Return only the list of positions."""
        
        messages = [{"role": "user", "content": instruction}]
        
        rh_token = os.getenv("RH_REFRESH_TOKEN")
        resp = self.client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=messages,
            betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
            mcp_servers=[{
                "type": "url",
                "url": self.mcp_url,
                "name": self.mcp_name,
                "authorization_token": rh_token,
            }]
        )
        
        # Parse positions from tool result
        positions = self._parse_positions_from_response(resp)
        return positions
    
    async def place_option_order(
        self,
        symbol: str,
        option_chain_id: str,
        quantity: int,
        order_type: str = "limit",
        limit_price: Optional[float] = None,
        direction: str = "buy_to_open",
    ) -> OrderResponse:
        """Place option order via MCP"""
        
        instruction = f"""Place this option order via place_option_order:
        - Symbol: {symbol}
        - Option chain ID: {option_chain_id}
        - Quantity: {quantity}
        - Direction: {direction}
        - Order type: {order_type}
        - Limit price: ${limit_price if limit_price else "market"}
        
        Execute immediately. Return order ID and status."""
        
        messages = [{"role": "user", "content": instruction}]
        
        rh_token = os.getenv("RH_REFRESH_TOKEN")
        resp = self.client.beta.messages.create(
            model="claude-opus-4-8",
            max_tokens=1000,
            messages=messages,
            betas=["mcp-client-2025-04-04", "prompt-caching-2024-07-31"],
            mcp_servers=[{
                "type": "url",
                "url": self.mcp_url,
                "name": self.mcp_name,
                "authorization_token": rh_token,
            }]
        )
        
        # Parse order result from MCP tool_result
        order_result = self._parse_order_from_response(resp)
        return order_result
    
    def _parse_positions_from_response(self, resp) -> List[Dict]:
        """Extract positions from MCP tool result"""
        for block in resp.content:
            if block.type in ("tool_result", "mcp_tool_result"):
                if hasattr(block, "content"):
                    content = block.content
                    if isinstance(content, list):
                        content_text = "\n".join(str(c) for c in content)
                    else:
                        content_text = str(content)
                    # Parse JSON positions from MCP response
                    try:
                        positions = json.loads(content_text)
                        return positions
                    except:
                        pass
        return []
    
    def _parse_order_from_response(self, resp) -> OrderResponse:
        """Extract order result from MCP tool result"""
        for block in resp.content:
            if block.type in ("tool_result", "mcp_tool_result"):
                if hasattr(block, "content"):
                    content = block.content
                    if isinstance(content, list):
                        content_text = "\n".join(str(c) for c in content)
                    else:
                        content_text = str(content)
                    
                    # Parse order ID and status
                    try:
                        result = json.loads(content_text)
                        return OrderResponse(
                            success=True,
                            order_id=result.get("order_id"),
                            message=f"Order placed: {result}"
                        )
                    except:
                        pass
        
        return OrderResponse(success=False, order_id=None, message="Failed to parse order result")
```

### Step 3: Integrate Dedup Checks

**In uw_bot.py execute_trade()**:

```python
async def execute_trade(self, alert, classification):
    symbol = alert.get("symbol")
    
    # CRITICAL: Fetch fresh positions (no caching)
    current_positions = await self.robinhood_mcp.get_positions()
    owned_symbols = [p["symbol"] for p in current_positions]
    
    # Dedup check: Skip if already owned
    if symbol in owned_symbols:
        logger.warning(f"❌ {symbol} already owned - skip duplicate purchase")
        return False
    
    # Safe to place order
    order_response = await self.robinhood_mcp.place_option_order(...)
    # ... rest of execution
```

### Step 4: Environment Setup

**Required for real MCP** (add to .env):

```bash
# Robinhood OAuth
RH_CLIENT_ID="your_client_id"
RH_REFRESH_TOKEN="your_refresh_token"

# Anthropic (for real MCP calls)
ANTHROPIC_API_KEY="your_api_key"
```

### Step 5: Swap Mock → Real

**In uw_config.py**:

```python
# Tue-Fri: Mock mode
EXECUTION_MODE = {
    "mock_mode": True,           # ← Change to False Week 2
    "paper_trading": False,
}

# Week 2: Real MCP
# EXECUTION_MODE = {
#     "mock_mode": False,        # Enable real MCP
#     "paper_trading": False,    # Or True for paper
# }
```

**In uw_bot.py**:

```python
# Tue-Fri
self.robinhood_mcp = RobinhoodMCPClient(use_mock=True)

# Week 2
# from anthropic import Anthropic
# from uw_robinhood_mcp_real import RobinhoodMCPExecutor
# client = Anthropic()  # Real Anthropic client
# self.robinhood_mcp = RobinhoodMCPExecutor(client)
```

---

## MCP Configuration (LOCKED - Week 2)

**Do NOT change these values**:

```
MCP Server URL:  https://agent.robinhood.com/mcp/trading
MCP Server Name: robinhood
OAuth URL:       (automatic, via RH_REFRESH_TOKEN)
API Version:     claude-opus-4-8
Beta Flags:      mcp-client-2025-04-04, prompt-caching-2024-07-31
```

**References**:
- bot.py lines 1233-1252 (MCP configuration)
- bot.py lines 1719-1750 (fresh position fetching)
- bot.py lines 1298-1328 (tool result parsing)

---

## Week 2 Integration Checklist

- [ ] Read bot.py stage3_execute() fully (lines 1075-1380)
- [ ] Extract MCP server config (LOCKED values)
- [ ] Extract tool-use loop logic (result parsing)
- [ ] Extract dedup checks (fresh position fetch)
- [ ] Create uw_robinhood_mcp_real.py
- [ ] Add Anthropic client initialization
- [ ] Update uw_bot.py to use real MCP
- [ ] Test with paper trading first
- [ ] Verify dedup prevents duplicate buys
- [ ] Test with Phase 1+2 integration

---

## Risk Mitigation

**Mock → Real Transition**:

1. **Keep mock as fallback**: If real MCP fails, revert to mock
2. **Paper trading first**: Test Week 2 with play money before live
3. **Dedup validation**: Confirm position fetch prevents duplicates
4. **Token monitoring**: Track MCP API costs (usually $0-10/month)

**Error Handling**:

```python
try:
    # Try real MCP
    order = await self.robinhood_mcp.place_option_order(...)
except Exception as e:
    logger.error(f"MCP failed: {e}")
    # Fallback to mock (testing) or error halt
    if self.use_mock:
        return False  # Halt trading
```

---

## Summary

**Tue-Fri (Week 1)**: Mock mode ✅
- Tests validate architecture (14/14 pass)
- No real money at risk
- No Robinhood OAuth needed

**Week 2**: Real MCP migration 📋
- Extract from bot.py stage3_execute
- Wire fresh position fetches (dedup)
- Add Anthropic client initialization
- Test with paper trading first
- Go live Week 3

**Status**: All infrastructure ready. MCP integration path clear. 🚀
