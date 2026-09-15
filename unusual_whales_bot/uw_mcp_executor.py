#!/usr/bin/env python3
"""
Executor bridge: uw_bot -> local MCP server -> Robinhood. No Claude anywhere.

ARCHITECTURE — reuses what was already built rather than inventing one.
    uw_bot.py
      -> UnusualWhalesMCP (uw_robinhood_mcp.py), mode LIVE
        -> MCPEquityExecutor (here)
          -> robinhood_mcp_server.py as a SUBPROCESS, JSON-RPC over stdio
            -> https://api.robinhood.com/orders/

The stdio client pattern is lifted from bot_mcp_client.py::MCPClient, which
already did exactly this and contains no Anthropic dependency.

WHAT WAS DELIBERATELY NOT USED, and why
  · local_mcp_executor.py and bot.py drive the MCP through the Anthropic API.
    Their docstrings claim "no Claude intermediary, $0", but both construct
    Anthropic() and let a model decide whether each order is placed. Wrong
    foundation for an unattended loop, and it is also BUY-ONLY: it filters
    action == "BUY" and only processes results when side == "buy", so exits
    would fail silently.
  · robinhood_live.py is a stub. Its MCP import is commented out and
    get_positions() logs "Fetching LIVE positions from Robinhood" before
    returning a hardcoded list from a past session.

TWO DEFECTS FIXED IN robinhood_mcp_server.py TO MAKE THIS WORK
  1. It read access_token from a JSON file once at IMPORT and never refreshed,
     so it ran on a stale token and would lose auth mid-session with no retry.
     Now exchanges the refresh token on demand, caches to just before expiry,
     and keeps the rotated refresh token.
  2. Its order payload omitted the `account` and `instrument` URLs, both of
     which Robinhood's /orders/ endpoint requires. It would have 400'd on every
     order — consistent with there being no record of it ever placing one.

SAFETY
dry_run defaults True; real orders need dry_run=False passed explicitly.
preflight() starts the server, lists tools and resolves the account WITHOUT
ordering. The live path in this project has never executed, and the Sep 8 audit
found ten defects in it while monitoring reported green — so being able to
exercise everything except the order matters.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "robinhood_mcp_server.py"


class StdioMCPClient:
    """JSON-RPC over a subprocess's stdin/stdout. Pattern from bot_mcp_client.py."""

    def __init__(self, server: Path = SERVER, timeout: int = 30):
        self.server = server
        self.timeout = timeout
        self.proc: Optional[subprocess.Popen] = None
        self._id = 0

    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        if not self.server.exists():
            logger.error(f"🚨 MCP server not found at {self.server}")
            return False
        try:
            self.proc = subprocess.Popen(
                [sys.executable, str(self.server)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, cwd=str(REPO),
                env={**os.environ},
            )
            # CONSUME THE STARTUP BANNER.
            #
            # robinhood_mcp_server.py prints its initialize response to stdout
            # BEFORE reading any request. Not consuming it puts every reply off
            # by one: tools/list returns the banner, get_portfolio returns the
            # tool list, and an order would read someone else's answer. The
            # original bot_mcp_client.py did this and I dropped it.
            banner = self.proc.stdout.readline()
            logger.info(f"✓ local MCP server started (stdio); banner: "
                        f"{banner.strip()[:80]}")
            return True
        except Exception as e:
            logger.error(f"🚨 could not start MCP server: {e}")
            return False

    def call(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        if not self.start():
            return None
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params or {}}
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except Exception as e:
            logger.error(f"🚨 MCP transport error: {e}")
            self.stop()
            return None
        if not line:
            # A dead server must be loud. Silence here would look like "no
            # orders today" rather than "execution is broken".
            err = ""
            try:
                if self.proc and self.proc.stderr:
                    err = self.proc.stderr.read()[:300]
            except Exception:
                pass
            logger.error(f"🚨 MCP server returned nothing (exited?). stderr: {err}")
            self.stop()
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            logger.error(f"🚨 unparseable MCP reply: {line[:200]}")
            return None

    def call_tool(self, name: str, args: Dict) -> Optional[Dict]:
        return self.call("tools/call", {"name": name, "arguments": args})

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None


class MCPEquityExecutor:
    """
    Satisfies the contract uw_robinhood_mcp.py expects of `mcp_executor`:

        await place_equity_order(symbol=, quantity=, side=,
                                 order_type=, limit_price=)
        -> {"success", "order_id", "message", "fill_price"}

    Handles BUY and SELL. That is not incidental — a bot that can enter and
    not exit fails every stop, target and EOD flatten, which is worse than one
    that never trades.
    """

    def __init__(self, account_number: Optional[str] = None, dry_run: bool = True):
        self.client = StdioMCPClient()
        self.account_number = account_number or os.getenv("RH_ACCOUNT_NUMBER")
        self.dry_run = dry_run
        if dry_run:
            logger.warning("🧪 MCPEquityExecutor DRY RUN — no orders sent")
        else:
            logger.warning("🚨 MCPEquityExecutor LIVE — real orders, real money")

    def preflight(self) -> Dict:
        out = {"dry_run": self.dry_run, "account_number": self.account_number,
               "server_started": False, "tools": None, "account": False}
        if not self.client.start():
            out["error"] = f"could not start {SERVER.name}"
            return out
        out["server_started"] = True
        if not self.account_number:
            out["error"] = "RH_ACCOUNT_NUMBER not set — refusing to guess an account"
            return out
        t = self.client.call("tools/list")
        if t:
            names = [x.get("name") for x in (t.get("result", {}).get("tools")
                                             or t.get("tools") or [])]
            out["tools"] = names
            out["has_place_equity_order"] = "place_equity_order" in names
        r = self.client.call_tool("get_portfolio", {})
        txt = ""
        if r:
            for c in ((r.get("result") or r).get("content") or []):
                if isinstance(c, dict):
                    txt += c.get("text", "")
        if txt and "error" not in txt.lower():
            out["account"] = True
            out["portfolio_probe"] = txt[:160]
        else:
            out["error"] = f"account/auth probe failed: {txt[:200] or 'no reply'}"
        out["ready"] = bool(out.get("account") and out.get("has_place_equity_order"))
        return out

    async def place_equity_order(self, symbol: str, quantity: float, side: str,
                                 order_type: str = "market",
                                 limit_price: Optional[float] = None) -> Dict:
        return await asyncio.to_thread(self._place, symbol, quantity, side,
                                       order_type, limit_price)

    def _place(self, symbol: str, quantity: float, side: str,
               order_type: str, limit_price: Optional[float]) -> Dict:
        def fail(msg):
            logger.error(f"🚨 order refused: {msg}")
            return {"success": False, "order_id": None, "message": msg,
                    "fill_price": None}

        side = str(side).lower()
        if side not in ("buy", "sell"):
            return fail(f"invalid side {side!r}")
        try:
            qty = float(quantity)
        except (TypeError, ValueError):
            return fail(f"invalid quantity {quantity!r}")
        if qty <= 0:
            return fail(f"non-positive quantity {qty}")
        if not self.account_number:
            return fail("no RH_ACCOUNT_NUMBER configured")

        if self.dry_run:
            logger.warning(f"🧪 DRY RUN — would place {side} {qty} {symbol}")
            return {"success": True, "order_id": "dryrun",
                    "message": "dry run — no order sent", "fill_price": None,
                    "dry_run": True}

        r = self.client.call_tool("place_equity_order", {
            "symbol": symbol.upper(), "quantity": qty, "side": side})
        if not r:
            return fail("no reply from the MCP server")

        txt = ""
        for c in ((r.get("result") or r).get("content") or []):
            if isinstance(c, dict):
                txt += c.get("text", "")
        try:
            d = json.loads(txt)
        except Exception:
            d = {}
        if d.get("status") == "success":
            logger.warning(f"🚀 LIVE order: {side} {qty} {symbol} → {d.get('order_id')}")
            return {"success": True, "order_id": d.get("order_id"),
                    "message": f"{side} {qty} {symbol} ({d.get('state')})",
                    "fill_price": None}
        return fail(f"order not accepted: {txt[:250] or 'empty reply'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ex = MCPEquityExecutor(dry_run=True)
    r = ex.preflight()
    print("\nPREFLIGHT — local MCP, no Claude")
    for k in ("account_number", "server_started", "tools",
              "has_place_equity_order", "account", "ready", "error"):
        if k in r:
            print(f"  {k:<24}{r[k]}")
    ex.client.stop()
