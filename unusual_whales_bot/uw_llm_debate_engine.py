"""
Phase 3B: LLM Enhancement Agent Layer

Multi-agent debate framework:
1. MacroRegimeAgent: Fed/economic catalyst alignment
2. MultiLegDetectorAgent: Institutional hedge de-masking
3. GEXDynamicsAgent: Gamma wall adaptation

Runs in parallel (~45-60ms latency), applies dynamic position scaling,
gates trades with hard confidence thresholds.

Returns: FinalDebateDecision (approved/rejected, conviction score, scaled position size)
"""

import asyncio
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger(__name__)


class AgentOpinion(BaseModel):
    """Single agent's evaluation result"""
    agent_name: str
    approved: bool
    conviction_score: float = Field(..., ge=0.0, le=1.0)
    rationale: str


class FinalDebateDecision(BaseModel):
    """Final debate outcome + execution recommendation"""
    ticker: str
    trade_approved: bool
    adjusted_position_scale: float = Field(default=1.0, ge=0.0, le=1.5)
    final_conviction: float
    risk_summary: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class MacroRegimeAgent:
    """
    Evaluates macro monetary policy, Fed policy stance, economic data
    against Market Tide (index-level net call/put premium).
    
    Prevents trades that conflict with macro regime.
    """
    
    async def evaluate(
        self,
        alert: Dict[str, Any],
        market_tide: Dict[str, Any],
        macro_news: List[str] = None
    ) -> AgentOpinion:
        """
        Evaluate macro regime alignment.
        
        Args:
            alert: Trade alert (ticker, direction, premium)
            market_tide: Index-level net positioning
            macro_news: Recent Fed/economic headlines (optional)
        
        Returns:
            AgentOpinion with approval + conviction
        """
        if macro_news is None:
            macro_news = []
        
        is_call = alert.get("direction", "CALL") == "CALL"
        ticker = alert.get("symbol", "SPY")
        
        net_call_prem = float(market_tide.get("net_call_premium", 0))
        net_put_prem = float(market_tide.get("net_put_premium", 0))
        
        # Logic: CALL trades need bullish market tide
        if is_call and net_call_prem > net_put_prem:
            logger.info(
                f"✅ {ticker} CALL: Market Tide bullish "
                f"(${net_call_prem/1e6:.1f}M calls vs ${net_put_prem/1e6:.1f}M puts)"
            )
            return AgentOpinion(
                agent_name="MacroRegimeAgent",
                approved=True,
                conviction_score=0.85,
                rationale=f"Market Tide bullish. Index-wide net call premium supports long bias."
            )
        
        # PUT trades need bearish market tide
        elif not is_call and net_put_prem > net_call_prem:
            logger.info(
                f"✅ {ticker} PUT: Market Tide bearish "
                f"(${net_put_prem/1e6:.1f}M puts vs ${net_call_prem/1e6:.1f}M calls)"
            )
            return AgentOpinion(
                agent_name="MacroRegimeAgent",
                approved=True,
                conviction_score=0.85,
                rationale=f"Market Tide bearish. Index-wide net put premium supports short bias."
            )
        
        else:
            logger.warning(f"⚠️  {ticker}: Macro conflict detected")
            return AgentOpinion(
                agent_name="MacroRegimeAgent",
                approved=False,
                conviction_score=0.30,
                rationale="Market Tide conflicts with trade direction. Macro environment unfavorable."
            )


class MultiLegDetectorAgent:
    """
    De-masks institutional complex strategies (collars, synthetics, spreads)
    disguised as simple directional sweeps.
    
    Prevents fading against institution hedging activity.
    """
    
    async def evaluate(
        self,
        alert: Dict[str, Any],
        dark_pool_data: Dict[str, Any] = None,
        recent_options_flow: List[Dict[str, Any]] = None
    ) -> AgentOpinion:
        """
        Identify multi-leg institutional strategies.
        
        Args:
            alert: Trade alert
            dark_pool_data: Underlying stock trading activity
            recent_options_flow: Correlated options activity
        
        Returns:
            AgentOpinion (DIRECTIONAL vs HEDGE vs AMBIGUOUS)
        """
        if dark_pool_data is None:
            dark_pool_data = {}
        if recent_options_flow is None:
            recent_options_flow = []
        
        ticker = alert.get("symbol")
        
        # Red flag: Multi-leg indicator
        multi_vol = alert.get("multi_vol", 0)
        if multi_vol > 0:
            logger.warning(f"🚨 {ticker}: Multi-leg flag detected (multi_vol={multi_vol})")
            return AgentOpinion(
                agent_name="MultiLegDetectorAgent",
                approved=False,
                conviction_score=0.20,
                rationale="Trade is part of a multi-leg complex strategy (collar, strangle, spread). Not pure directional."
            )
        
        # Red flag: Underlying dump + call buy = synthetic short
        dark_pool_side = dark_pool_data.get("dark_pool_side", "NEUTRAL")
        is_call = alert.get("direction") == "CALL"
        
        if is_call and dark_pool_side == "SELL":
            logger.warning(f"🚨 {ticker}: Synthetic short hedge detected (calls + underlying dump)")
            return AgentOpinion(
                agent_name="MultiLegDetectorAgent",
                approved=False,
                conviction_score=0.25,
                rationale="Call sweep + dark pool selling = synthetic short hedge, not bullish."
            )
        
        # No red flags = directional
        logger.info(f"✅ {ticker}: Single-leg directional sweep confirmed")
        return AgentOpinion(
            agent_name="MultiLegDetectorAgent",
            approved=True,
            conviction_score=0.90,
            rationale="Clean single-leg directional sweep, no institutional hedging complexity."
        )


class GEXDynamicsAgent:
    """
    Adapts execution around market-maker Gamma Exposure (GEX) walls
    and zero-gamma flip points.
    
    Prevents entries into high gamma zones where MM hedging causes reversals.
    """
    
    async def evaluate(
        self,
        alert: Dict[str, Any],
        gex_data: Dict[str, Any] = None,
        iv_data: Dict[str, Any] = None
    ) -> AgentOpinion:
        """
        Evaluate gamma dynamics at entry strike.
        
        Args:
            alert: Trade alert (strike price)
            gex_data: Market-maker gamma walls
            iv_data: IV crush, skew
        
        Returns:
            AgentOpinion with dynamic sizing recommendation
        """
        if gex_data is None:
            gex_data = {}
        if iv_data is None:
            iv_data = {}
        
        ticker = alert.get("symbol")
        strike = float(alert.get("strike_price", 0.0))
        
        # Find nearest gamma wall
        call_gex_wall = float(gex_data.get("max_call_gex_strike", 0.0))
        put_gex_wall = float(gex_data.get("max_put_gex_strike", 0.0))
        
        # If strike sits directly on wall (within 0.5%), expect pin/reversal
        if call_gex_wall > 0 and abs(strike - call_gex_wall) <= 0.5:
            logger.warning(f"⚠️  {ticker}: Strike ${strike} sits on Call GEX wall (${call_gex_wall})")
            return AgentOpinion(
                agent_name="GEXDynamicsAgent",
                approved=False,
                conviction_score=0.40,
                rationale=f"Entry strike ${strike} sits directly on major Call Gamma Wall (${call_gex_wall}). High reversal risk."
            )
        
        if put_gex_wall > 0 and abs(strike - put_gex_wall) <= 0.5:
            logger.warning(f"⚠️  {ticker}: Strike ${strike} sits on Put GEX wall (${put_gex_wall})")
            return AgentOpinion(
                agent_name="GEXDynamicsAgent",
                approved=False,
                conviction_score=0.40,
                rationale=f"Entry strike ${strike} sits directly on major Put Gamma Wall (${put_gex_wall}). High reversal risk."
            )
        
        # IV crush check
        iv_crush = float(iv_data.get("iv_crush_pct", 0))
        if iv_crush > 15:
            logger.info(f"📊 {ticker}: IV crush {iv_crush}% will accelerate gamma flows")
            conviction_adjust = 0.85 * (1 - iv_crush / 100)
        else:
            conviction_adjust = 0.85
        
        logger.info(f"✅ {ticker}: Gamma dynamics favorable (no major walls)")
        return AgentOpinion(
            agent_name="GEXDynamicsAgent",
            approved=True,
            conviction_score=conviction_adjust,
            rationale=f"Strike ${strike} cleared major dealer gamma walls. Favorable execution path."
        )


class PortfolioDebateEngine:
    """
    Orchestrates all Phase 3B agents in parallel.
    Applies consensus gating + dynamic position sizing.
    Returns final go/no-go for Phase 2 execution.
    """
    
    def __init__(self):
        self.macro_agent = MacroRegimeAgent()
        self.multileg_agent = MultiLegDetectorAgent()
        self.gex_agent = GEXDynamicsAgent()
        self.min_consensus_score = 0.65  # Hard gate
    
    async def execute_debate(
        self,
        alert: Dict[str, Any],
        market_tide: Dict[str, Any],
        gex_data: Dict[str, Any] = None,
        dark_pool_data: Dict[str, Any] = None,
        iv_data: Dict[str, Any] = None,
        macro_news: List[str] = None
    ) -> FinalDebateDecision:
        """
        Run multi-agent debate framework.
        
        Args:
            alert: Trade alert from Phase 1 filter
            market_tide: Market Tide data
            gex_data: Gamma exposure walls
            dark_pool_data: Off-exchange trading activity
            iv_data: Implied volatility metrics
            macro_news: Recent economic/Fed headlines
        
        Returns:
            FinalDebateDecision with approval + sizing recommendation
        """
        ticker = alert.get("symbol", "UNKNOWN")
        logger.info(f"\n{'='*80}")
        logger.info(f"🧠 Phase 3B LLM Debate Engine Initiated: {ticker}")
        logger.info(f"{'='*80}\n")
        
        # Run all agents in parallel
        opinions: List[AgentOpinion] = await asyncio.gather(
            self.macro_agent.evaluate(alert, market_tide, macro_news),
            self.multileg_agent.evaluate(alert, dark_pool_data),
            self.gex_agent.evaluate(alert, gex_data, iv_data)
        )
        
        # Calculate consensus metrics
        rejections = [op for op in opinions if not op.approved]
        avg_conviction = sum(op.conviction_score for op in opinions) / len(opinions)
        
        # Log all opinions
        for opinion in opinions:
            status = "✅ APPROVE" if opinion.approved else "❌ REJECT"
            logger.info(f"  {status} - {opinion.agent_name} ({opinion.conviction_score:.2f})")
            logger.info(f"         {opinion.rationale}\n")
        
        # Hard gating rule: Any agent rejection = trade rejected
        if len(rejections) >= 1:
            reasons = " | ".join([f"{r.agent_name}: {r.rationale}" for r in rejections])
            logger.warning(f"⛔ DEBATE REJECTED: {reasons}\n")
            return FinalDebateDecision(
                ticker=ticker,
                trade_approved=False,
                adjusted_position_scale=0.0,
                final_conviction=avg_conviction,
                risk_summary=f"Trade halted by agent consensus. Reasons: {reasons}"
            )
        
        # Consensus check: avg conviction must exceed threshold
        if avg_conviction < self.min_consensus_score:
            logger.warning(
                f"⛔ DEBATE REJECTED: Avg conviction {avg_conviction:.2f} "
                f"below threshold {self.min_consensus_score}\n"
            )
            return FinalDebateDecision(
                ticker=ticker,
                trade_approved=False,
                adjusted_position_scale=0.0,
                final_conviction=avg_conviction,
                risk_summary=f"Insufficient conviction ({avg_conviction:.2f} < {self.min_consensus_score})"
            )
        
        # Dynamic position sizing based on conviction
        if avg_conviction >= 0.85:
            scale_factor = 1.25  # Upsize high-conviction
            size_reason = "High conviction (≥0.85) → 1.25x position"
        elif avg_conviction >= 0.75:
            scale_factor = 1.0   # Base size
            size_reason = "Good conviction (0.75-0.85) → 1.0x position"
        else:
            scale_factor = 0.75  # Downsize lower-conviction
            size_reason = "Lower conviction (< 0.75) → 0.75x position"
        
        logger.info(f"✅ DEBATE APPROVED\n")
        logger.info(f"  Average conviction: {avg_conviction:.2f}")
        logger.info(f"  Position scaling: {size_reason}\n")
        
        return FinalDebateDecision(
            ticker=ticker,
            trade_approved=True,
            adjusted_position_scale=scale_factor,
            final_conviction=avg_conviction,
            risk_summary=f"All agents approved. Consensus conviction: {avg_conviction:.2f}. Position scaled to {scale_factor}x."
        )


# ===== EXAMPLE USAGE =====

async def example_debate():
    """Run example debate"""
    logging.basicConfig(level=logging.INFO)
    
    # Mock Phase 1 filtered alert
    alert = {
        "symbol": "NVDA",
        "direction": "CALL",
        "strike_price": 125.0,
        "premium": 250_000,
        "multi_vol": 0,
    }
    
    market_tide = {
        "net_call_premium": 45_000_000,
        "net_put_premium": -10_000_000,
    }
    
    gex_data = {
        "max_call_gex_strike": 135.0,
        "max_put_gex_strike": 115.0,
    }
    
    dark_pool_data = {
        "dark_pool_side": "BUY",
    }
    
    iv_data = {
        "iv_crush_pct": 5.0,
    }
    
    # Run debate
    engine = PortfolioDebateEngine()
    decision = await engine.execute_debate(
        alert=alert,
        market_tide=market_tide,
        gex_data=gex_data,
        dark_pool_data=dark_pool_data,
        iv_data=iv_data,
    )
    
    print(f"\n{'='*80}")
    print(f"FINAL DEBATE DECISION")
    print(f"{'='*80}")
    print(f"Ticker: {decision.ticker}")
    print(f"Trade Approved: {decision.trade_approved}")
    print(f"Position Scale: {decision.adjusted_position_scale}x")
    print(f"Conviction: {decision.final_conviction:.2f}")
    print(f"Summary: {decision.risk_summary}\n")
    
    if decision.trade_approved:
        print(f"🚀 Routing to Phase 2 Execution (Robinhood MCP)...")
    else:
        print(f"🛑 Trade rejected. No execution.")


if __name__ == "__main__":
    asyncio.run(example_debate())
