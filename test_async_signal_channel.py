#!/usr/bin/env python3
"""
Parallel Signal Channel: Institutional + Macro Intelligence
Async scanner for 13-F filings, options sweeps, Fed data
Feeds signals to macro_triggers.json queue (non-blocking to main bot)

Run every 60 seconds via cron:
  * * * * * /path/to/venv/bin/python3 /path/to/test_async_signal_channel.py
"""

import json
import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path
import requests
from typing import Dict, List, Optional, Any
import re
import signal

# ============================================================================
# SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger(__name__)

# Use absolute path resolution to prevent cron from writing to home dir
TRADING_BOT_DIR = Path(__file__).parent.resolve()
MACRO_TRIGGERS_FILE = TRADING_BOT_DIR / "macro_triggers.json"
CONFIG_FILE = TRADING_BOT_DIR / "config.json"

logger.debug(f"Bot dir: {TRADING_BOT_DIR}")
logger.debug(f"Triggers file: {MACRO_TRIGGERS_FILE}")

# ============================================================================
# MACRO DATA FETCHER (CACHED)
# ============================================================================

class MacroDataFetcher:
    """Fetch Fed rates, VIX with caching (5 min TTL)"""

    CACHE_FILE = TRADING_BOT_DIR / ".macro_cache.json"
    CACHE_TTL_SEC = 300  # 5 minutes

    @staticmethod
    def _load_cache() -> Dict[str, Any]:
        """Load cached macro data if fresh"""
        if MacroDataFetcher.CACHE_FILE.exists():
            try:
                with open(MacroDataFetcher.CACHE_FILE, 'r') as f:
                    cache = json.load(f)
                    timestamp = cache.get("timestamp")
                    if timestamp:
                        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        age = (datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds()
                        if age < MacroDataFetcher.CACHE_TTL_SEC:
                            return cache.get("data", {})
            except:
                pass
        return {}

    @staticmethod
    def _save_cache(data: Dict[str, Any]) -> None:
        """Save macro data with timestamp"""
        try:
            cache = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": data
            }
            with open(MacroDataFetcher.CACHE_FILE, 'w') as f:
                json.dump(cache, f)
        except:
            pass

    @staticmethod
    def _load_fred_key() -> Optional[str]:
        """Load FRED API key from config (required for FRED API access)"""
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get("fred_api_key")
        except:
            logger.warning("FRED API key not found in config.json (skipping Fed rate)")
            return None

    @staticmethod
    def get_fed_rate() -> Optional[Dict[str, Any]]:
        """Current Fed funds rate (cached 5 min) - REQUIRES valid FRED API key"""
        cache = MacroDataFetcher._load_cache()
        if cache.get("fed_rate"):
            logger.debug("Using cached Fed rate")
            return cache["fed_rate"]

        # CRITICAL: FRED API requires valid API key (free from stlouisfed.org/api)
        fred_key = MacroDataFetcher._load_fred_key()
        if not fred_key:
            logger.debug("Fed rate fetch skipped (no FRED API key)")
            return None

        try:
            url = "https://api.stlouisfed.org/fred/series/FEDFUNDS/observations"
            params = {
                "series_id": "FEDFUNDS",
                "api_key": fred_key,
                "file_type": "json",  # CRITICAL: Request JSON format
                "limit": 1,
                "sort_order": "desc"
            }
            resp = requests.get(url, params=params, timeout=3)
            resp.raise_for_status()
            data = resp.json()

            if data.get("observations"):
                latest = data["observations"][0]
                result = {
                    "rate": float(latest["value"]),
                    "date": latest["date"],
                    "trend": "UP" if float(latest["value"]) > 4.5 else "DOWN"
                }
                # Cache it
                cache["fed_rate"] = result
                MacroDataFetcher._save_cache(cache)
                logger.info(f"Fed rate: {result['rate']:.2f}% ({result['trend']})")
                return result
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in [400, 401]:
                logger.error(f"FRED API auth failed (check fred_api_key): {e}")
            else:
                logger.debug(f"Fed rate fetch failed: {e}")
        except Exception as e:
            logger.debug(f"Fed rate fetch error: {e}")
        return None

    @staticmethod
    def get_vix() -> Optional[Dict[str, float]]:
        """VIX from cache or Yahoo Finance (cached 5 min)"""
        cache = MacroDataFetcher._load_cache()
        if cache.get("vix"):
            return cache["vix"]

        try:
            url = "https://query1.finance.yahoo.com/v7/finance/quote"
            params = {"symbols": "^VIX"}
            resp = requests.get(url, params=params, timeout=3)
            resp.raise_for_status()
            data = resp.json()

            if data.get("quoteResponse", {}).get("result"):
                quote = data["quoteResponse"]["result"][0]
                result = {
                    "vix": quote.get("regularMarketPrice", 0),
                    "change": quote.get("regularMarketChange", 0),
                    "trend": "HIGH_VOLATILITY" if quote.get("regularMarketPrice", 0) > 20 else "LOW_VOLATILITY"
                }
                cache["vix"] = result
                MacroDataFetcher._save_cache(cache)
                return result
        except Exception as e:
            logger.debug(f"VIX fetch failed (will retry next cycle): {e}")
        return None


# ============================================================================
# 13-F FILING SCANNER (OPTIMIZED)
# ============================================================================

class SEC13FScanner:
    """
    Efficient 13-F scanner: Only checks for NEW filings since last scan.
    Caches last scan timestamp to avoid re-scanning old data.
    Completes in <5 seconds for top filers.
    """

    CACHE_FILE = TRADING_BOT_DIR / ".13f_scan_cache.json"
    SCAN_INTERVAL_HOURS = 4  # Only rescan every 4 hours (quarterly filings)

    MAJOR_FILERS = [
        ("0001018724", "Berkshire Hathaway"),
        ("0001564408", "Sequoia Capital"),
        ("0001649395", "Renaissance Technologies"),
    ]

    @staticmethod
    def _load_cache() -> Dict[str, Any]:
        """Load last scan timestamp"""
        if SEC13FScanner.CACHE_FILE.exists():
            try:
                with open(SEC13FScanner.CACHE_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"last_scan": None, "known_filings": {}}

    @staticmethod
    def _save_cache(cache: Dict[str, Any]) -> None:
        """Save scan state"""
        try:
            with open(SEC13FScanner.CACHE_FILE, 'w') as f:
                json.dump(cache, f)
        except:
            pass

    @staticmethod
    def _should_scan() -> bool:
        """Check if enough time elapsed since last scan"""
        cache = SEC13FScanner._load_cache()
        last_scan = cache.get("last_scan")

        if not last_scan:
            return True

        try:
            last_dt = datetime.fromisoformat(last_scan)
            elapsed = (datetime.utcnow() - last_dt).total_seconds() / 3600
            return elapsed >= SEC13FScanner.SCAN_INTERVAL_HOURS
        except:
            return True

    @staticmethod
    def fetch_13f_changes() -> List[Dict[str, Any]]:
        """
        OPTIMIZED: Only scan if 4+ hours since last scan.
        Quarterly filings don't change intraday, so skip redundant checks.
        """
        signals = []

        # Skip if recently scanned
        if not SEC13FScanner._should_scan():
            logger.debug("13-F scan skipped (last scan within 4 hours)")
            return signals

        cache = SEC13FScanner._load_cache()
        known_filings = cache.get("known_filings", {})

        try:
            for cik, filer_name in SEC13FScanner.MAJOR_FILERS:
                try:
                    # CRITICAL: SEC EDGAR enforces User-Agent requirement (HTTP 403 without it)
                    headers = {
                        "User-Agent": "RebelsTradingBot/1.0 (admin@rebelstrading.com)"
                    }

                    # Single EDGAR API call per filer (~1 sec per filer)
                    url = "https://www.sec.gov/cgi-bin/browse-edgar"
                    params = {
                        "action": "getcompany",
                        "CIK": cik,
                        "type": "13F-HR",
                        "count": 1,  # Only fetch most recent
                        "output": "json"
                    }

                    resp = requests.get(url, params=params, headers=headers, timeout=4)
                    resp.raise_for_status()
                    data = resp.json()

                    if data.get("filings", {}).get("recent", {}).get("filing"):
                        latest = data["filings"]["recent"]["filing"][0]
                        filing_date = latest.get("filingDate", "")
                        accession = latest.get("accessionNumber", "")

                        # Check if NEW (not in cache)
                        if accession not in known_filings:
                            # NEW FILING DETECTED
                            signal = {
                                "type": "13F_FILING_NEW",
                                "filer": filer_name,
                                "filer_cik": cik,
                                "filing_date": filing_date,
                                "accession": accession,
                                "timestamp": datetime.utcnow().isoformat() + "Z",
                                "ttl_minutes": 1440,  # 24 hours (quarterly news)
                                "note": f"New 13-F from {filer_name} - check position changes"
                            }
                            signals.append(signal)
                            known_filings[accession] = filing_date
                            logger.info(f"✅ NEW 13-F: {filer_name} ({filing_date})")
                        else:
                            logger.debug(f"13-F cached: {filer_name} ({filing_date})")

                except requests.Timeout:
                    logger.warning(f"13-F scan timeout for {filer_name}")
                except Exception as e:
                    logger.debug(f"13-F scan error for {filer_name}: {e}")

        except Exception as e:
            logger.warning(f"13-F scanner error: {e}")

        # Update cache with new scan timestamp
        cache["known_filings"] = known_filings
        cache["last_scan"] = datetime.utcnow().isoformat() + "Z"
        SEC13FScanner._save_cache(cache)

        return signals


# ============================================================================
# OPTIONS SWEEP SCANNER
# ============================================================================

class OptionsSweeperScanner:
    """Monitor options sweeps for unusual institutional activity"""

    @staticmethod
    def fetch_option_sweeps() -> List[Dict[str, Any]]:
        """
        Scan for unusual options activity.
        Uses free sources (Unusual Whales public data, etc.)
        """
        signals = []

        try:
            # Try Unusual Whales RSS feed (free public)
            # Note: This is a simplified approach; production would use paid API

            url = "https://www.unusualwhales.com/api/unusual/option_sweeps"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
            }

            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()

            # Parse sweeps if available
            if resp.text:
                # Unusual Whales may return HTML or JSON depending on endpoint
                # For now, log that we attempted
                logger.debug("Options sweep scan completed (limited free data)")

        except Exception as e:
            logger.debug(f"Options sweep fetch failed (expected - requires paid API): {e}")

        return signals


# ============================================================================
# SIGNAL EVALUATOR (LLM-based)
# ============================================================================

class SignalEvaluator:
    """Evaluate signal quality using Claude (local MCP or API)"""

    def __init__(self):
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load config with API key"""
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}

    def evaluate_13f_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evaluate 13-F filing signal.
        Returns enriched signal with confidence score.
        """
        try:
            # For now, return basic evaluation
            # In production, would call Claude to analyze filing

            evaluated = signal.copy()
            evaluated.update({
                "confidence_score": 65,  # Medium confidence for 13-F
                "bias": "NEUTRAL",  # 13-Fs are backward-looking
                "actionable_trigger": False,  # 13-F requires manual verification
                "reason": "13-F filing detected; requires manual review of position changes"
            })

            return evaluated

        except Exception as e:
            logger.error(f"13-F evaluation failed: {e}")
            return None

    def evaluate_options_sweep(self, sweep: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evaluate options sweep signal.
        Returns enriched signal with confidence and bias.
        """
        try:
            # Placeholder for LLM evaluation
            # Production: Use Claude API to analyze sweep context

            evaluated = sweep.copy()
            evaluated.update({
                "confidence_score": 78,
                "bias": "BULLISH",
                "actionable_trigger": True,
                "reason": "Large call sweep detected with institutional volume"
            })

            return evaluated

        except Exception as e:
            logger.error(f"Options sweep evaluation failed: {e}")
            return None


# ============================================================================
# SIGNAL QUEUE MANAGER
# ============================================================================

class SignalQueueManager:
    """Manage macro_triggers.json queue with TTL"""

    @staticmethod
    def load_triggers() -> Dict[str, List[Dict[str, Any]]]:
        """Load existing triggers from queue file"""
        if MACRO_TRIGGERS_FILE.exists():
            try:
                with open(MACRO_TRIGGERS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {"active": [], "meta": {}}
        return {"active": [], "meta": {}}

    @staticmethod
    def save_triggers(triggers: Dict[str, Any]) -> None:
        """
        Persist triggers to queue file ATOMICALLY.
        Prevents bot from reading partially-written file during concurrent writes.
        Uses tmp file + atomic rename to ensure consistency.
        """
        tmp_file = MACRO_TRIGGERS_FILE.with_suffix(".tmp")
        try:
            # Write to temporary file first
            with open(tmp_file, 'w') as f:
                json.dump(triggers, f, indent=2)

            # Atomic replace: no partial reads possible
            tmp_file.replace(MACRO_TRIGGERS_FILE)

            logger.info(f"Saved {len(triggers.get('active', []))} active triggers (atomic write)")
        except Exception as e:
            logger.error(f"Failed to save triggers: {e}")
            # Cleanup tmp file if write failed
            try:
                if tmp_file.exists():
                    tmp_file.unlink()
            except:
                pass

    @staticmethod
    def add_signal(signal: Dict[str, Any]) -> None:
        """Add new signal to queue, removing expired ones"""
        triggers = SignalQueueManager.load_triggers()

        # Remove expired signals
        now = datetime.utcnow()
        active = []

        for sig in triggers.get("active", []):
            try:
                ts = datetime.fromisoformat(sig["timestamp"].replace("Z", "+00:00"))
                ttl_min = sig.get("ttl_minutes", 60)
                age_min = (now - ts.replace(tzinfo=None)).total_seconds() / 60

                if age_min < ttl_min:
                    active.append(sig)
                else:
                    logger.debug(f"Expired signal: {sig.get('type')} from {sig['timestamp']}")
            except:
                active.append(sig)  # Keep if unparseable

        # Add new signal
        active.append(signal)

        triggers["active"] = active
        triggers["meta"] = {
            "last_update": datetime.utcnow().isoformat() + "Z",
            "total_signals": len(active),
            "signal_types": list(set(s.get("type", "UNKNOWN") for s in active))
        }

        SignalQueueManager.save_triggers(triggers)

    @staticmethod
    def get_signal_for_symbol(symbol: str) -> Optional[Dict[str, Any]]:
        """Retrieve active signal for a symbol (if any)"""
        triggers = SignalQueueManager.load_triggers()

        for sig in triggers.get("active", []):
            if sig.get("symbol") == symbol:
                return sig

        return None


# ============================================================================
# MAIN SCAN LOOP (OPTIMIZED FOR 30-SECOND EXECUTION)
# ============================================================================

import signal

class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Scan timeout (30 seconds)")

def run_signal_scan() -> None:
    """Execute one scan cycle in <30 seconds: fetch + evaluate + queue"""

    # Set 30-second timeout to prevent hanging
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(30)

    start_time = datetime.utcnow()

    try:
        logger.info("=== PARALLEL SIGNAL CHANNEL SCAN ===")

        # Step 1: Fetch macro data (quick, cached)
        logger.info("Fetching macro data...")
        fed_rate = MacroDataFetcher.get_fed_rate()
        vix = MacroDataFetcher.get_vix()

        if fed_rate:
            logger.info(f"  Fed Rate: {fed_rate['rate']:.2f}% ({fed_rate['trend']})")
        if vix:
            logger.info(f"  VIX: {vix['vix']:.1f} ({vix['trend']})")

        # Step 2: Scan 13-F filings (optimized: only if 4h elapsed)
        logger.info("Scanning 13-F filings...")
        filings_13f = SEC13FScanner.fetch_13f_changes()
        logger.info(f"  Found {len(filings_13f)} new 13-F signals")

        # Step 3: Scan options (skipped if API unavailable)
        logger.info("Scanning options activity...")
        options_sweeps = OptionsSweeperScanner.fetch_option_sweeps()
        logger.info(f"  Found {len(options_sweeps)} sweep signals")

        # Step 4: Evaluate and queue
        evaluator = SignalEvaluator()

        for filing in filings_13f:
            evaluated = evaluator.evaluate_13f_signal(filing)
            if evaluated:
                SignalQueueManager.add_signal(evaluated)
                logger.info(f"  ✅ Queued 13-F signal: {evaluated.get('type')}")

        for sweep in options_sweeps:
            evaluated = evaluator.evaluate_options_sweep(sweep)
            if evaluated:
                SignalQueueManager.add_signal(evaluated)
                logger.info(f"  ✅ Queued options signal: {evaluated.get('type')}")

        # Step 5: Report queue status
        triggers = SignalQueueManager.load_triggers()
        elapsed_sec = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"\n✨ Queue Status: {triggers['meta'].get('total_signals', 0)} active signals (completed in {elapsed_sec:.1f}s)")
        for sig_type in triggers['meta'].get('signal_types', []):
            count = sum(1 for s in triggers.get('active', []) if s.get('type') == sig_type)
            logger.info(f"   {sig_type}: {count}")

        logger.info("=== SCAN COMPLETE ===\n")

    except TimeoutException as e:
        logger.warning(f"⏱️  {e} - scan stopped to avoid blocking bot")
    except Exception as e:
        logger.error(f"Scan error: {e}")
    finally:
        signal.alarm(0)  # Cancel alarm


# ============================================================================
# BOT INTEGRATION EXAMPLE
# ============================================================================

def example_bot_integration():
    """
    Example: How main bot checks for parallel signals during execution

    In bot_production_final.py run_cycle():
        macro_signal = SignalQueueManager.get_signal_for_symbol("NVDA")
        if macro_signal and macro_signal.get("confidence_score", 0) >= 70:
            logger.info(f"Macro signal aligned: {macro_signal['reason']}")
            # Boost position sizing or skip entry if conflicting
    """
    pass


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    try:
        run_signal_scan()
    except KeyboardInterrupt:
        logger.info("Signal channel stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        # Don't exit - allow bot to continue even if parallel channel fails
        sys.exit(0)
