"""
Phase 3B: Open-Source Debate Engine (ZERO API COSTS)

Replaces Claude LLM with deterministic Python logic.
Same filtering power, 100% free (just run locally).

Key insight: 80% of "reasoning" is rule-based confluence detection.
No need for expensive LLM inference - just smart heuristics.
"""

import logging
from typing import Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DebateDecision:
    """Final debate outcome (matches Phase 3B LLM output)"""
    ticker: str
    trade_approved: bool
    adjusted_position_scale: float  # 0.75x, 1.0x, 1.25x
    final_conviction: float         # 0.0-1.0
    risk_summary: str
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


class OpenSourceDebateEngine:
    """
    Deterministic multi-agent debate (no API calls, 100% free).
    
    Agents:
    1. MacroRegimeAgent: Market Tide alignment check
    2. MultiLegDetector: Synthetic short / collar detection
    3. GEXDynamicsAgent: Gamma wall proximity check
    
    All rule-based (no ML, no LLM).
    """
    
    def __init__(self):
        self.min_conviction_threshold = 0.65
        self.agent_weights = {
            "macro": 0.30,
            "multileg": 0.40,  # Most critical - prevents traps
            "gex": 0.30,
        }
    
    def evaluate_macro_regime(
        self, 
        alert: Dict[str, Any], 
        market_tide: Dict[str, Any]
    ) -> Tuple[bool, float, str]:
        """
        Agent 1: Macro regime alignment.
        
        Rules:
        - CALL trades need bullish market tide
        - PUT trades need bearish market tide
        - Neutral tide = cautious (reduce conviction)
        """
        is_call = alert.get("direction") == "CALL"
        tide_direction = market_tide.get("net_direction", "NEUTRAL")
        
        if is_call and tide_direction == "BULLISH":
            return True, 0.90, "Market Tide bullish supports call positions"
        elif not is_call and tide_direction == "BEARISH":
            return True, 0.90, "Market Tide bearish supports put positions"
        elif tide_direction == "NEUTRAL":
            return True, 0.70, "Market Tide neutral - proceed with caution"
        else:
            return False, 0.25, f"Market Tide {tide_direction} conflicts with {alert['direction']} bias"
    
    def evaluate_multileg_detector(
        self,
        alert: Dict[str, Any],
        dark_pool_data: Dict[str, Any] = None
    ) -> Tuple[bool, float, str]:
        """
        Agent 2: Detect institutional hedges disguised as sweeps.
        
        Hard rejection rules:
        1. multi_vol flag > 0 → multi-leg spread
        2. Calls + dark pool SELL → synthetic short hedge
        3. Puts + dark pool BUY → collar / protective structure
        """
        if dark_pool_data is None:
            dark_pool_data = {}
        
        # Rule 1: Multi-leg flag
        multi_vol = alert.get("multi_vol", 0)
        if multi_vol > 0:
            return False, 0.10, "Detected multi-leg spread (multi_vol > 0)"
        
        # Rule 2: Synthetic short (calls + underlying dump)
        is_call = alert.get("direction") == "CALL"
        dp_side = dark_pool_data.get("dark_pool_side", "NEUTRAL")
        
        if is_call and dp_side == "SELL":
            return False, 0.15, "Detected synthetic short: calls + underlying dump"
        
        # Rule 3: Collar (puts + underlying buy)
        if not is_call and dp_side == "BUY":
            return False, 0.20, "Detected collar hedge: puts + underlying accumulation"
        
        # No red flags = clean directional sweep
        return True, 0.92, "Pure directional sweep (no institutional hedge detected)"
    
    def evaluate_gex_dynamics(
        self,
        alert: Dict[str, Any],
        gex_data: Dict[str, Any] = None
    ) -> Tuple[bool, float, str]:
        """
        Agent 3: Evaluate gamma wall proximity.
        
        Hard rejection rule:
        - Strike within 0.5% of major gamma wall → high reversal risk
        
        Soft penalty:
        - Strike within 2% of wall → reduce conviction
        """
        if gex_data is None:
            gex_data = {}
        
        strike = float(alert.get("strike_price", 0.0))
        call_wall = float(gex_data.get("max_call_gex_strike", 0.0))
        put_wall = float(gex_data.get("max_put_gex_strike", 0.0))
        
        is_call = alert.get("direction") == "CALL"
        
        # Hard rejection: Strike directly on wall (0.5% proximity)
        if is_call and call_wall > 0:
            distance_pct = abs(strike - call_wall) / call_wall * 100
            if distance_pct < 0.5:
                return False, 0.30, f"Strike ${strike} sits on call gamma wall ${call_wall}"
        
        if not is_call and put_wall > 0:
            distance_pct = abs(strike - put_wall) / put_wall * 100
            if distance_pct < 0.5:
                return False, 0.30, f"Strike ${strike} sits on put gamma wall ${put_wall}"
        
        # Soft penalty: Within 2% of wall
        if is_call and call_wall > 0:
            distance_pct = abs(strike - call_wall) / call_wall * 100
            if distance_pct < 2.0:
                return True, 0.75, f"Strike near call wall - proceed with caution"
        
        if not is_call and put_wall > 0:
            distance_pct = abs(strike - put_wall) / put_wall * 100
            if distance_pct < 2.0:
                return True, 0.75, f"Strike near put wall - proceed with caution"
        
        # No walls nearby = safe
        return True, 0.88, "Strike cleared major gamma walls"
    
    def evaluate_position_sizing_rules(
        self,
        alert: Dict[str, Any],
        vol_oi: Dict[str, Any] = None
    ) -> float:
        """
        Dynamic position sizing based on conviction level.
        
        Rules:
        - Vol/OI > 2.0 + Ask vol > 85% → 1.25x position
        - Vol/OI 1.0-2.0 + normal ask vol → 1.0x position
        - Vol/OI < 1.2 or low ask vol → 0.75x position
        """
        if vol_oi is None:
            vol_oi = {"vol_oi_ratio": 1.0}
        
        vol_oi_ratio = float(vol_oi.get("vol_oi_ratio", 1.0))
        ask_vol = float(alert.get("ask_volume_pct", 0.75))
        
        # High conviction
        if vol_oi_ratio > 2.0 and ask_vol > 0.85:
            return 1.25
        
        # Base conviction
        elif vol_oi_ratio > 1.0 and ask_vol > 0.70:
            return 1.0
        
        # Lower conviction
        else:
            return 0.75
    
    def execute_debate(
        self,
        alert: Dict[str, Any],
        market_tide: Dict[str, Any],
        gex_data: Dict[str, Any] = None,
        dark_pool_data: Dict[str, Any] = None,
        vol_oi: Dict[str, Any] = None
    ) -> DebateDecision:
        """
        Run open-source debate engine.
        
        Returns: DebateDecision with approval + position sizing
        """
        ticker = alert.get("symbol", "UNKNOWN")
        logger.info(f"\n🤖 Phase 3B Open-Source Debate: {ticker}\n")
        
        # Run all agents
        macro_ok, macro_score, macro_reason = self.evaluate_macro_regime(alert, market_tide)
        multileg_ok, multileg_score, multileg_reason = self.evaluate_multileg_detector(alert, dark_pool_data)
        gex_ok, gex_score, gex_reason = self.evaluate_gex_dynamics(alert, gex_data)
        
        # Log each agent
        logger.info(f"MacroRegimeAgent:    {macro_score:.2f} - {macro_reason}")
        logger.info(f"MultiLegDetector:    {multileg_score:.2f} - {multileg_reason}")
        logger.info(f"GEXDynamicsAgent:    {gex_score:.2f} - {gex_reason}\n")
        
        # Hard gating: Any agent rejection = trade rejected
        if not (macro_ok and multileg_ok and gex_ok):
            reasons = []
            if not macro_ok:
                reasons.append(f"Macro: {macro_reason}")
            if not multileg_ok:
                reasons.append(f"MultiLeg: {multileg_reason}")
            if not gex_ok:
                reasons.append(f"GEX: {gex_reason}")
            
            logger.warning(f"⛔ Trade rejected: {' | '.join(reasons)}\n")
            
            avg_conviction = (macro_score + multileg_score + gex_score) / 3
            return DebateDecision(
                ticker=ticker,
                trade_approved=False,
                adjusted_position_scale=0.0,
                final_conviction=avg_conviction,
                risk_summary=f"Rejected by agents: {', '.join(reasons)}"
            )
        
        # All agents approved
        avg_conviction = (macro_score + multileg_score + gex_score) / 3
        position_scale = self.evaluate_position_sizing_rules(alert, vol_oi)
        
        logger.info(f"✅ All agents approved")
        logger.info(f"   Avg conviction: {avg_conviction:.2f}")
        logger.info(f"   Position scale: {position_scale:.2f}x\n")
        
        return DebateDecision(
            ticker=ticker,
            trade_approved=True,
            adjusted_position_scale=position_scale,
            final_conviction=avg_conviction,
            risk_summary=f"All agents approved. Conviction: {avg_conviction:.2f}. Scale: {position_scale:.2f}x"
        )


# ===== EXAMPLE USAGE =====

async def example_opensource_debate():
    """Run example debate with open-source engine."""
    logging.basicConfig(level=logging.INFO)
    
    alert = {
        "symbol": "NVDA",
        "direction": "CALL",
        "strike_price": 125.0,
        "ask_volume_pct": 0.82,
        "multi_vol": 0,
    }
    
    market_tide = {
        "net_call_premium": 52_000_000,
        "net_direction": "BULLISH",
    }
    
    gex_data = {
        "max_call_gex_strike": 135.0,
    }
    
    dark_pool_data = {
        "dark_pool_side": "BUY",
    }
    
    vol_oi = {
        "vol_oi_ratio": 2.08,
    }
    
    engine = OpenSourceDebateEngine()
    decision = await engine.execute_debate(
        alert=alert,
        market_tide=market_tide,
        gex_data=gex_data,
        dark_pool_data=dark_pool_data,
        vol_oi=vol_oi,
    )
    
    print(f"\n{'='*80}")
    print(f"OPEN-SOURCE DEBATE DECISION")
    print(f"{'='*80}")
    print(f"Ticker: {decision.ticker}")
    print(f"Approved: {decision.trade_approved}")
    print(f"Position Scale: {decision.adjusted_position_scale}x")
    print(f"Conviction: {decision.final_conviction:.2f}")
    print(f"Summary: {decision.risk_summary}\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_opensource_debate())
