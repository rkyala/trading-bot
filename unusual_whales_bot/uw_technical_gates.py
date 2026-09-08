#!/usr/bin/env python3
"""
Technical Gates 9-11: Production-Ready Price Confirmation Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Calculates MA20, RSI(14), and VWAP dynamically from price tick/candle data
and applies confidence scaling to Tier 2 trades.

Production hardening:
- Direction normalization (call/CALL/BUY_CALL all work)
- Real OHLCV calculations with pandas/numpy
- Graceful fallback handling for sparse/missing data
- Symmetric confidence adjustments
"""

import logging
import pandas as pd
import numpy as np
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class TechnicalGates:
    """Production Technical Confirmation Engine for Tier 2 Options Flow"""

    def __init__(self, api_client):
        self.api_client = api_client

    def _normalize_direction(self, direction: str) -> str:
        """Normalizes variant direction strings to standard 'CALL' or 'PUT'."""
        d = str(direction).upper().strip()
        if "CALL" in d or d == "C" or "BULL" in d:
            return "CALL"
        elif "PUT" in d or d == "P" or "BEAR" in d:
            return "PUT"
        return "CALL"  # Default fallback

    # =========================================================================
    # GATE 9: MOVING AVERAGE ALIGNMENT
    # =========================================================================
    async def gate_9_ma_alignment(
        self, symbol: str, alert_direction: str, price: float
    ) -> Tuple[bool, float]:
        """
        Gate 9: Moving Average Alignment

        Bullish: Price above MA20 (uptrend)
        Bearish: Price below MA20 (downtrend)
        """
        direction = self._normalize_direction(alert_direction)
        try:
            ma_20 = await self._get_moving_average(symbol, period=20)

            if ma_20 is None or ma_20 <= 0:
                logger.warning(f"⚠️ Gate 9 ({symbol}): MA20 unavailable. Using neutral fallback.")
                return True, 0.50

            if direction == "CALL":
                if price > ma_20:
                    logger.info(f"✅ Gate 9 ({symbol}): Price ${price:.2f} > MA20 ${ma_20:.2f}")
                    return True, 0.90
                elif price > ma_20 * 0.98:
                    logger.info(f"⚠️ Gate 9 ({symbol}): Price ${price:.2f} near MA20 ${ma_20:.2f}")
                    return True, 0.70
                else:
                    logger.warning(f"❌ Gate 9 ({symbol}): Price ${price:.2f} < MA20 ${ma_20:.2f} (Downtrend)")
                    return False, 0.30

            else:  # PUT
                if price < ma_20:
                    logger.info(f"✅ Gate 9 ({symbol}): Price ${price:.2f} < MA20 ${ma_20:.2f}")
                    return True, 0.90
                elif price < ma_20 * 1.02:
                    logger.info(f"⚠️ Gate 9 ({symbol}): Price ${price:.2f} near MA20 ${ma_20:.2f}")
                    return True, 0.70
                else:
                    logger.warning(f"❌ Gate 9 ({symbol}): Price ${price:.2f} > MA20 ${ma_20:.2f} (Uptrend)")
                    return False, 0.30

        except Exception as e:
            logger.error(f"❌ Gate 9 error on {symbol}: {e}")
            return True, 0.50

    # =========================================================================
    # GATE 10: RSI MOMENTUM
    # =========================================================================
    async def gate_10_rsi_momentum(
        self, symbol: str, alert_direction: str
    ) -> Tuple[bool, float]:
        """
        Gate 10: RSI Momentum Check

        Avoid overbought (RSI > 70) and oversold (RSI < 30)
        Ideal: Bullish 40-70, Bearish 30-60
        """
        direction = self._normalize_direction(alert_direction)
        try:
            rsi_14 = await self._get_rsi(symbol, period=14)

            if rsi_14 is None:
                logger.warning(f"⚠️ Gate 10 ({symbol}): RSI14 unavailable. Using neutral fallback.")
                return True, 0.50

            if direction == "CALL":
                if 40.0 <= rsi_14 <= 70.0:
                    logger.info(f"✅ Gate 10 ({symbol}): RSI {rsi_14:.1f} in ideal bullish zone (40-70)")
                    return True, 0.95
                elif 30.0 <= rsi_14 < 80.0:
                    logger.info(f"⚠️ Gate 10 ({symbol}): RSI {rsi_14:.1f} acceptable but extended")
                    return True, 0.65
                else:
                    logger.warning(f"❌ Gate 10 ({symbol}): RSI {rsi_14:.1f} extreme (<30 or >80)")
                    return False, 0.20

            else:  # PUT
                if 30.0 <= rsi_14 <= 60.0:
                    logger.info(f"✅ Gate 10 ({symbol}): RSI {rsi_14:.1f} in ideal bearish zone (30-60)")
                    return True, 0.95
                elif 20.0 <= rsi_14 < 70.0:
                    logger.info(f"⚠️ Gate 10 ({symbol}): RSI {rsi_14:.1f} acceptable but extended")
                    return True, 0.65
                else:
                    logger.warning(f"❌ Gate 10 ({symbol}): RSI {rsi_14:.1f} extreme (<20 or >70)")
                    return False, 0.20

        except Exception as e:
            logger.error(f"❌ Gate 10 error on {symbol}: {e}")
            return True, 0.50

    # =========================================================================
    # GATE 11: VWAP ALIGNMENT
    # =========================================================================
    async def gate_11_vwap_alignment(
        self, symbol: str, alert_direction: str, price: float
    ) -> Tuple[bool, float]:
        """
        Gate 11: VWAP Alignment

        VWAP = Volume-Weighted Average Price (smart money entry cost)
        Bullish: Price > VWAP (smart money profitable)
        Bearish: Price < VWAP (smart money profitable)
        """
        direction = self._normalize_direction(alert_direction)
        try:
            vwap = await self._get_vwap(symbol)

            if vwap is None or vwap <= 0:
                logger.warning(f"⚠️ Gate 11 ({symbol}): VWAP unavailable. Using neutral fallback.")
                return True, 0.50

            if direction == "CALL":
                if price > vwap:
                    logger.info(f"✅ Gate 11 ({symbol}): Price ${price:.2f} > VWAP ${vwap:.2f}")
                    return True, 0.95
                elif price > vwap * 0.98:
                    logger.info(f"⚠️ Gate 11 ({symbol}): Price ${price:.2f} near VWAP ${vwap:.2f}")
                    return True, 0.70
                else:
                    logger.warning(f"❌ Gate 11 ({symbol}): Price ${price:.2f} < VWAP ${vwap:.2f}")
                    return False, 0.30

            else:  # PUT
                if price < vwap:
                    logger.info(f"✅ Gate 11 ({symbol}): Price ${price:.2f} < VWAP ${vwap:.2f}")
                    return True, 0.95
                elif price < vwap * 1.02:
                    logger.info(f"⚠️ Gate 11 ({symbol}): Price ${price:.2f} near VWAP ${vwap:.2f}")
                    return True, 0.70
                else:
                    logger.warning(f"❌ Gate 11 ({symbol}): Price ${price:.2f} > VWAP ${vwap:.2f}")
                    return False, 0.30

        except Exception as e:
            logger.error(f"❌ Gate 11 error on {symbol}: {e}")
            return True, 0.50

    # =========================================================================
    # COMBINED CONFIDENCE AGGREGATOR
    # =========================================================================
    async def calculate_technical_confidence(
        self, symbol: str, alert_direction: str, price: float
    ) -> float:
        """
        Continuous, ATR-normalised confidence from Gates 9-11.

        REPLACES the previous `0.75 baseline + per-gate nudge` scheme, which
        did not discriminate: measured on live flow it produced only 90/96/100%
        and blocked zero trades. A pass added ~+0.09 and a "marginal" +0.04, so
        three marginal gates still scored ~0.87 (full size).

        Now: each gate scores continuously in [0,1], distances are normalised
        by ATR so thresholds mean the same thing across price levels, the
        combination is a weighted mean with NO baseline, and hard vetoes
        (position >1.5 ATR against trend, exhausted RSI) collapse the score.

        Confidence range: 0.0 (veto) to 1.0 (strongest)
        """
        result = await self.evaluate_detailed(symbol, alert_direction, price)
        return result["confidence"]

    async def evaluate_detailed(
        self, symbol: str, alert_direction: str, price: float
    ) -> dict:
        """
        Same scoring as calculate_technical_confidence, but returns the raw
        indicator values and per-gate scores as well.

        Needed so the feature logger can capture decision-time technicals
        without recomputing them (which would risk logging values from a
        slightly later moment than the decision actually used).
        """
        from uw_gate_scoring import score_all

        direction = self._normalize_direction(alert_direction)
        is_bullish = direction == "CALL"

        try:
            ma20 = await self._get_moving_average(symbol, period=20)
            rsi14 = await self._get_rsi(symbol, period=14)
            vwap = await self._get_vwap(symbol)

            atr = None
            try:
                atr = self.api_client.get_atr(symbol)
            except Exception:
                pass
            if not atr or atr <= 0:
                # Fall back to a percentage proxy so the gates still function.
                atr = price * 0.02

            result = score_all(price, ma20, rsi14, vwap, atr, is_bullish)

            # Decision-time indicator snapshot for the feature logger.
            result["technicals"] = {
                "ma20": ma20,
                "rsi14": rsi14,
                "vwap": vwap,
                "atr": atr,
                "ma20_dist_atr": ((price - ma20) / atr) if ma20 and atr else None,
                "vwap_dist_atr": ((price - vwap) / atr) if vwap and atr else None,
            }

        except Exception as e:
            logger.error(f"❌ Confidence aggregation error on {symbol}: {e}")
            return {"confidence": 0.50, "vetoed": False, "technicals": {},
                    "ma": {}, "rsi": {}, "vwap": {}}

        if result["vetoed"]:
            logger.warning(
                f"⛔ {symbol} {direction} VETOED — "
                f"MA:{result['ma']['reason']} | RSI:{result['rsi']['reason']} | "
                f"VWAP:{result['vwap']['reason']}"
            )
            return result

        logger.info(
            f"📐 {symbol} {direction} conf={result['confidence']:.0%} "
            f"[MA {result['ma']['score']:.2f} ({result['ma']['reason']}) | "
            f"RSI {result['rsi']['score']:.2f} ({result['rsi']['reason']}) | "
            f"VWAP {result['vwap']['score']:.2f} ({result['vwap']['reason']})]"
        )
        return result

    # =========================================================================
    # TECHNICAL DATA CALCULATIONS
    # =========================================================================
    async def _get_moving_average(self, symbol: str, period: int = 20) -> Optional[float]:
        """Calculates Simple Moving Average from historical daily close prices."""
        try:
            # Fetch historical OHLCV candles
            candles = await self.api_client.get_historical_candles(
                symbol, interval="day", limit=period + 5
            )

            if not candles or len(candles) < period:
                logger.warning(f"⚠️ Insufficient candles for MA{period}: got {len(candles) if candles else 0}")
                return None

            closes = [float(c.get("close", 0)) for c in candles[-period:]]
            if not closes or any(c <= 0 for c in closes):
                return None

            return float(np.mean(closes))

        except Exception as e:
            logger.error(f"MA{period} calculation error for {symbol}: {e}")
            return None

    async def _get_rsi(self, symbol: str, period: int = 14) -> Optional[float]:
        """Calculates 14-period Relative Strength Index (RSI)."""
        try:
            candles = await self.api_client.get_historical_candles(
                symbol, interval="day", limit=period + 10
            )

            if not candles or len(candles) < period + 1:
                logger.warning(f"⚠️ Insufficient candles for RSI{period}")
                return None

            df = pd.DataFrame(candles)
            if "close" not in df.columns:
                return None

            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)

            avg_gain = gain.rolling(window=period).mean().iloc[-1]
            avg_loss = loss.rolling(window=period).mean().iloc[-1]

            if pd.isna(avg_gain) or pd.isna(avg_loss) or avg_loss == 0:
                return 100.0 if avg_gain > 0 else 0.0

            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
            return float(rsi)

        except Exception as e:
            logger.error(f"RSI{period} calculation error for {symbol}: {e}")
            return None

    async def _get_vwap(self, symbol: str) -> Optional[float]:
        """Calculates Intraday Volume-Weighted Average Price (VWAP)."""
        try:
            # Query intraday ticks (1m or 5m) for current session
            ticks = await self.api_client.get_intraday_ticks(symbol, interval="5m")

            if not ticks or len(ticks) < 2:
                logger.warning(f"⚠️ Insufficient intraday ticks for VWAP")
                return None

            df = pd.DataFrame(ticks)
            required_cols = {"high", "low", "close", "volume"}
            if not required_cols.issubset(df.columns):
                logger.warning(f"⚠️ Missing columns for VWAP: {required_cols - set(df.columns)}")
                return None

            typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
            total_pv = (typical_price * df["volume"]).sum()
            total_volume = df["volume"].sum()

            if total_volume == 0 or total_pv <= 0:
                return None

            return float(total_pv / total_volume)

        except Exception as e:
            logger.error(f"VWAP calculation error for {symbol}: {e}")
            return None
