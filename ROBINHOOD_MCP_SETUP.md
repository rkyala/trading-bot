# Official Robinhood MCP Server Setup

## Step 1: Install Official Server

```bash
# Install globally
npm install -g @modelcontextprotocol/server-robinhood

# Or use npx directly (no install needed)
npx @modelcontextprotocol/server-robinhood
```

## Step 2: Configure Environment

The official server reads credentials from environment:

```bash
# Export your OAuth tokens
export ROBINHOOD_CLIENT_ID=LtLiNmbs9owbYfWgBlC68Z2VujIPuvGoAiSYr8xW
export ROBINHOOD_ACCESS_TOKEN=eyJhbGciOiJFUzI1NiIs...
export ROBINHOOD_REFRESH_TOKEN=38DkyvSQbb5J6ud6qVJdBERh4c8jQ4
```

Or create `.env.robinhood`:

```
ROBINHOOD_CLIENT_ID=LtLiNmbs9owbYfWgBlC68Z2VujIPuvGoAiSYr8xW
ROBINHOOD_ACCESS_TOKEN=eyJhbGciOiJFUzI1NiIs...
ROBINHOOD_REFRESH_TOKEN=38DkyvSQbb5J6ud6qVJdBERh4c8jQ4
```

## Step 3: Run Official Server

**Terminal 1 (Server):**
```bash
cd ~/trading_bot

# Option A: With environment variables
export $(cat .env.robinhood | xargs)
npx @modelcontextprotocol/server-robinhood

# Option B: Direct with npx
npx -y @modelcontextprotocol/server-robinhood
```

**Terminal 2 (Bot):**
```bash
cd ~/trading_bot
python3 bot_with_official_mcp.py
```

## Step 4: Bot Client Code

The bot talks to the official server via stdio JSON-RPC:

```python
import json
import subprocess

process = subprocess.Popen(
    ["npx", "@modelcontextprotocol/server-robinhood"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# Send JSON-RPC request
request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "place_equity_order",
        "arguments": {
            "symbol": "NVDA",
            "quantity": 50,
            "side": "buy"
        }
    }
}

process.stdin.write(json.dumps(request) + "\n")
process.stdin.flush()
response = json.loads(process.stdout.readline())
```

## Complete Setup Checklist

- [ ] Have Node.js installed (`node --version`)
- [ ] OAuth tokens in `.env.robinhood` or exported
- [ ] Official server installed or accessible via `npx`
- [ ] Bot script ready (`bot_with_official_mcp.py`)
- [ ] Start server in one terminal
- [ ] Start bot in another terminal

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  Bot (Python) ←→ Official Robinhood MCP Server (Node.js)   │
│                    ↓                                         │
│              Robinhood API (authenticated)                  │
│                                                             │
│  • Bot sends JSON-RPC over stdio                           │
│  • Official server handles MCP protocol                    │
│  • Server authenticates with Robinhood OAuth              │
│  • Live trading enabled                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Troubleshooting

**"command not found: npx"**
→ Install Node.js from nodejs.org

**"Could not resolve authentication method"**
→ Export ROBINHOOD_ACCESS_TOKEN and ROBINHOOD_REFRESH_TOKEN

**Server not responding**
→ Check server started in Terminal 1, view its output

## Next Steps

1. Ensure Node.js is installed
2. Start official server (Terminal 1)
3. Run bot (Terminal 2)
4. Monitor logs for successful trades
