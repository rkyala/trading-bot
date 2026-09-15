#!/usr/bin/env python3
"""
Executor bridge: uw_bot -> Robinhood Trading MCP. Local process, no Claude.

    uw_bot.py
      -> UnusualWhalesMCP (uw_robinhood_mcp.py), mode LIVE
        -> MCPEquityExecutor (here)
          -> JSON-RPC over HTTPS to agent.robinhood.com/mcp/trading

MCP is an open protocol. This module is an MCP CLIENT written in plain Python —
Claude is one client of that protocol, not a required one. No Anthropic SDK, no
API key, no model in the order path, and it runs unattended under launchd.

WHY NOT THE LOCAL REST SERVER (robinhood_mcp_server.py)
Because these credentials cannot use it. Decoding the access token's claims:

    meta:  {"oid": "...", "on": "Robinhood Trading MCP"}
    scope: "internal"   level2_access: true   options: true

It is an AGENT token minted for the MCP surface. Measured 2026-09-14:

    api.robinhood.com/portfolios/     401  "rejected client id"
    agent.robinhood.com/mcp/trading   200  full initialize, 73 tools

So the legacy REST wrapper returns 401 on every call no matter how correct its
payloads are. That also explains why there is no record of that server ever
placing an order — it never could with these credentials.

WHY NOT bot.py / local_mcp_executor.py
Both reach the same MCP through the Anthropic API, so a model decides whether
each order is placed and every order costs tokens. local_mcp_executor is also
BUY-ONLY (filters action == "BUY", processes results only when side == "buy"),
so every stop, target and EOD flatten would fail silently.

REFRESH TOKENS ARE SINGLE USE
Verified: exchanging one returns a replacement and invalidates the original
immediately. A token was destroyed during development by exchanging twice and
discarding the rotation. Every rotation is now persisted to .env.local
atomically, and the file — not os.environ — is the source of truth, because the
environment is a snapshot taken before any rotation.

SAFETY
dry_run defaults True. preflight() performs OAuth, initialize, tools/list and
get_accounts WITHOUT ordering — everything a real order does except the order.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / ".env.local"
TOKEN_URL = "https://api.robinhood.com/oauth2/token/"
MCP_URL = os.getenv("RH_MCP_URL", "https://agent.robinhood.com/mcp/trading")
PROTOCOL_VERSION = "2025-03-26"
TOKEN_MARGIN_S = 300


def _from_env_file(key: str) -> Optional[str]:
    try:
        with open(ENV_FILE) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _cred(*names: str) -> Optional[str]:
    """File first — it holds the live value after any rotation."""
    for n in names:
        v = _from_env_file(n)
        if v:
            return v
    for n in names:
        if os.getenv(n):
            return os.getenv(n)
    return None


def _persist_refresh_token(token: str) -> None:
    """Atomically write a rotated refresh token back to .env.local."""
    try:
        lines, seen = [], False
        if ENV_FILE.exists():
            with open(ENV_FILE) as fh:
                for line in fh:
                    if line.startswith("RH_REFRESH_TOKEN="):
                        lines.append(f"RH_REFRESH_TOKEN={token}\n")
                        seen = True
                    else:
                        lines.append(line)
        if not seen:
            lines.append(f"RH_REFRESH_TOKEN={token}\n")
        fd, tmp = tempfile.mkstemp(dir=str(ENV_FILE.parent))
        with os.fdopen(fd, "w") as fh:
            fh.writelines(lines)
        os.chmod(tmp, 0o600)
        os.replace(tmp, ENV_FILE)
        logger.info("✓ rotated refresh token persisted")
    except Exception as e:
        # LOUD: losing this means no login after the next restart.
        logger.error(f"🚨 CRITICAL: could not persist rotated refresh token: {e}")


class MCPError(RuntimeError):
    pass


class RobinhoodMCP:
    """Minimal MCP client over Streamable HTTP: initialize, tools/list, tools/call."""

    def __init__(self, url: str = MCP_URL, timeout: int = 30):
        self.url, self.timeout = url, timeout
        self._access: Optional[str] = None
        self._expires = 0.0
        self._session: Optional[str] = None
        self._ready = False
        self._id = 0

    def access_token(self) -> Optional[str]:
        if self._access and time.time() < self._expires:
            return self._access
        cid = _cred("RH_CLIENT_ID", "ROBINHOOD_CLIENT_ID")
        rt = _cred("RH_REFRESH_TOKEN", "ROBINHOOD_REFRESH_TOKEN")
        if not (cid and rt):
            logger.error("🚨 No Robinhood credentials in .env.local or environment")
            return None
        try:
            r = requests.post(TOKEN_URL, timeout=self.timeout, data={
                "grant_type": "refresh_token", "refresh_token": rt, "client_id": cid})
        except Exception as e:
            logger.error(f"🚨 OAuth request failed: {e}")
            return None
        if r.status_code != 200:
            logger.error(f"🚨 OAuth rejected: HTTP {r.status_code} {r.text[:160]}")
            return None
        d = r.json()
        self._access = d.get("access_token")
        if d.get("refresh_token"):
            _persist_refresh_token(d["refresh_token"])
        self._expires = time.time() + max(60, int(d.get("expires_in", 3600)) - TOKEN_MARGIN_S)
        return self._access

    def _headers(self) -> Optional[Dict[str, str]]:
        t = self.access_token()
        if not t:
            return None
        h = {"Authorization": f"Bearer {t}", "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": PROTOCOL_VERSION}
        if self._session:
            h["Mcp-Session-Id"] = self._session
        return h

    def _rpc(self, method: str, params: Optional[Dict] = None,
             notify: bool = False, _retried: bool = False) -> Optional[Dict]:
        h = self._headers()
        if not h:
            raise MCPError("not authenticated")
        body: Dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        r = requests.post(self.url, headers=h, json=body, timeout=self.timeout)
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        if sid:
            self._session = sid
        if r.status_code == 401:
            # RE-AUTHENTICATE AND RETRY ONCE. A 401 used to raise here with the
            # dead token still cached, so the process stayed poisoned for its
            # whole life — every subsequent order, INCLUDING EVERY EXIT,
            # failed. On 2026-09-15 the bot held five live positions and could
            # not have stopped out of any of them.
            #
            # Refresh tokens are single use, so ANY other OAuth exchange —
            # another process, a diagnostic script — rotates the credential and
            # invalidates this session's access token. That is not an
            # exceptional case to fail on; it is a normal thing that happens,
            # and the only correct response is to get a new token.
            if not _retried:
                logger.warning("401 from MCP — re-authenticating and retrying")
                self._access = None
                self._expires = 0.0
                self._session = None
                self._ready = False
                return self._rpc(method, params, notify, _retried=True)
            raise MCPError("401 from MCP after re-authentication — credentials "
                           "are invalid, not merely stale")
        if r.status_code >= 400:
            raise MCPError(f"HTTP {r.status_code}: {r.text[:200]}")
        if notify:
            return None
        # Streamable HTTP answers as SSE; plain JSON is also accepted.
        for line in r.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        d = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if "error" in d:
                        raise MCPError(str(d["error"])[:200])
                    return d.get("result")
        try:
            d = r.json()
        except ValueError:
            raise MCPError(f"unparseable reply: {r.text[:160]}")
        if "error" in d:
            raise MCPError(str(d["error"])[:200])
        return d.get("result")

    def connect(self) -> Dict:
        if self._ready:
            return {}
        res = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "uw-bot", "version": "1.0"}}) or {}
        self._rpc("notifications/initialized", {}, notify=True)
        self._ready = True
        logger.info(f"✓ MCP connected: {(res.get('serverInfo') or {}).get('name')} "
                    f"v{(res.get('serverInfo') or {}).get('version')}")
        return res

    def tools(self) -> List[Dict]:
        self.connect()
        return (self._rpc("tools/list") or {}).get("tools") or []

    def call(self, name: str, args: Dict) -> Dict:
        self.connect()
        res = self._rpc("tools/call", {"name": name, "arguments": args}) or {}
        if res.get("isError"):
            raise MCPError(f"{name}: {str(res.get('content'))[:300]}")
        return res

    @staticmethod
    def text(res: Dict) -> str:
        return "\n".join(c.get("text", "") for c in (res.get("content") or [])
                         if isinstance(c, dict) and c.get("type") == "text")


class MCPEquityExecutor:
    """
    Satisfies the `mcp_executor` contract in uw_robinhood_mcp.py:

        await place_equity_order(symbol=, quantity=, side=,
                                 order_type=, limit_price=)
        -> {"success", "order_id", "message", "fill_price"}

    BUY and SELL both. A bot that enters and cannot exit fails every stop,
    target and EOD flatten, which is worse than one that never trades.
    """

    def __init__(self, account_number: Optional[str] = None, dry_run: bool = True):
        self.mcp = RobinhoodMCP()
        self.account_number = (account_number or _cred("RH_ACCOUNT_NUMBER"))
        self.dry_run = dry_run
        logger.warning("🧪 MCPEquityExecutor DRY RUN — no orders sent" if dry_run
                       else "🚨 MCPEquityExecutor LIVE — real orders, real money")

    def preflight(self) -> Dict:
        out = {"dry_run": self.dry_run, "account_number": self.account_number,
               "auth": False, "connected": False, "tools": 0, "account": False}
        try:
            if not self.mcp.access_token():
                out["error"] = "OAuth failed — reissue the refresh token"
                return out
            out["auth"] = True
            info = self.mcp.connect()
            out["connected"] = True
            out["server"] = (info.get("serverInfo") or {}).get("name")
            names = [t.get("name") for t in self.mcp.tools()]
            out["tools"] = len(names)
            out["has_place_equity_order"] = "place_equity_order" in names
            if not self.account_number:
                out["error"] = "RH_ACCOUNT_NUMBER not set — refusing to guess an account"
                return out
            txt = self.mcp.text(self.mcp.call("get_accounts", {}))
            out["account"] = self.account_number in txt
            if not out["account"]:
                out["error"] = f"account {self.account_number} not visible to this token"
            out["ready"] = bool(out["account"] and out.get("has_place_equity_order"))
        except Exception as e:
            out["error"] = str(e)
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

        # ARGUMENT NAMES COME FROM THE SERVER'S OWN SCHEMA, not assumption.
        # tools/list reports for place_equity_order:
        #   required: account_number, symbol, side, type
        #   accepts : quantity, dollar_amount, limit_price, stop_price,
        #             time_in_force, market_hours, ref_id
        # It had been sending "price", which this server rejects — every limit
        # order would have failed. review_equity_order takes the same set MINUS
        # ref_id, and passing it there returns
        #   -32602 unexpected additional properties ["ref_id"]
        # which is what broke dry-run pricing.
        # FRACTIONAL QUANTITIES CANNOT USE LIMIT ORDERS.
        #
        # Robinhood rejects them outright:
        #   API error 400: "Limit order quantity cannot include fractional
        #   shares."
        # This bot sizes by DOLLARS (allow_fractional_shares, $500/entry), so
        # almost every quantity is fractional — 0.7544 META, 0.35 SHOP. On the
        # first live session every single order was refused by this, after the
        # ATR bug had already been fixed.
        #
        # Downgrading to market is the correct resolution rather than rounding:
        # rounding to whole shares breaks dollar-based sizing (one SNDK share
        # is $1,795 against a $500 target), which is the defect fractional
        # sizing was introduced to fix. It also matches the friction already
        # measured — ~$0.42 per round trip assumed crossing the spread, which
        # is what a market order does.
        order_type = str(order_type).lower()
        if order_type == "limit" and abs(qty - round(qty)) > 1e-9:
            logger.info(
                f"↩️  {symbol}: {qty} is fractional — limit orders cannot be "
                f"fractional on Robinhood, sending market instead")
            order_type = "market"
            limit_price = None

        args = {"account_number": self.account_number, "symbol": symbol.upper(),
                "side": side, "quantity": str(qty), "type": order_type,
                "time_in_force": "gfd"}
        if order_type == "limit":
            if not limit_price:
                return fail("limit order without a limit_price")
            args["limit_price"] = f"{float(limit_price):.2f}"

        if self.dry_run:
            # Return a REAL quote as the fill price. Returning None left the
            # position manager without an entry price, so a dry-run session
            # would produce positions it could not value, stop or report — the
            # run would "succeed" and the P&L would be meaningless.
            #
            # review_equity_order is the MCP's own validation: it prices the
            # order and returns order_checks WITHOUT placing anything, so a dry
            # run exercises Robinhood's real argument validation too.
            fill, checks = None, None
            try:
                rv = self.mcp.call("review_equity_order",
                                   {k: v for k, v in args.items() if k != "ref_id"})
                d = json.loads(self.mcp.text(rv)).get("data") or {}
                q = d.get("quote_data") or {}
                checks = d.get("order_checks")
                bid, ask = _f(q.get("bid_price")), _f(q.get("ask_price"))
                last = _f(q.get("last_trade_price"))
                # Cross the spread the way a market order does, but only when
                # the book is sane — the after-hours book showed bid 13.71 /
                # ask 17.45 on a $13.85 stock (27%), which would model a fill
                # that could never happen in the session the bot trades.
                if bid and ask and last and (ask - bid) / last <= 0.02:
                    fill = ask if side == "buy" else bid
                else:
                    fill = last
            except Exception as e:
                logger.warning(f"dry-run review failed for {symbol}: {str(e)[:120]}")
            logger.warning(f"🧪 DRY RUN — would place {side} {qty} {symbol} "
                           f"{order_type}" + (f" ~${fill:.2f}" if fill else "")
                           + (f" checks={checks}" if checks else ""))
            return {"success": True, "order_id": f"dryrun-{uuid.uuid4().hex[:8]}",
                    "message": "dry run — validated, not sent"
                               + (f" (~${fill:.2f})" if fill else ""),
                    "fill_price": fill, "dry_run": True}

        try:
            txt = self.mcp.text(self.mcp.call(
                "place_equity_order", {**args, "ref_id": str(uuid.uuid4())}))
        except MCPError as e:
            return fail(f"place_equity_order failed: {e}")
        except Exception as e:
            return fail(f"unexpected error: {e}")

        # Order id was coming back "unknown" on every live fill because this
        # assumed the id sat at the top level or one deep under "data". The MCP
        # wraps it differently, and without the id a fill cannot be reconciled
        # against get_equity_orders — which is the only way to measure real
        # slippage. Search the structure instead of guessing its shape.
        def _find_id(obj, depth=0):
            if depth > 4:
                return None
            if isinstance(obj, dict):
                for k in ("id", "order_id"):
                    v = obj.get(k)
                    if isinstance(v, str) and len(v) >= 8:
                        return v
                for v in obj.values():
                    got = _find_id(v, depth + 1)
                    if got:
                        return got
            elif isinstance(obj, list):
                for v in obj[:5]:
                    got = _find_id(v, depth + 1)
                    if got:
                        return got
            return None

        oid = None
        try:
            oid = _find_id(json.loads(txt))
        except Exception:
            pass
        logger.warning(f"🚀 LIVE order: {side} {qty} {symbol} → {oid or 'id unknown'}")
        return {"success": True, "order_id": oid,
                "message": txt[:400] or f"{side} {qty} {symbol}", "fill_price": None}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ex = MCPEquityExecutor(dry_run=True)
    r = ex.preflight()
    print("\nPREFLIGHT — local MCP client, no Claude")
    for k in ("account_number", "auth", "connected", "server", "tools",
              "has_place_equity_order", "account", "ready", "error"):
        if k in r:
            print(f"  {k:<24}{r[k]}")
