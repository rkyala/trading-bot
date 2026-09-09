# Training-data archive — 2026-09-09 (Wed)

UW options bot, PAPER mode, $25,000 session equity. Branch `feature/uw`, HEAD `0230611`.
76 cycles, 08:57–14:45 CDT. 25 entries, 20 exits, realised **−$24.00** (4W / 14L / 2 flat).

Archived 15:2x CDT. Verified free of live credentials before writing.

---

## READ THIS BEFORE TRAINING ON ANY OF IT

Large parts of today's data were produced by components that were **broken for
part or all of the session**. Nine silent failures were fixed today, several
mid-session, so the same file can contain artifact rows and valid rows
separated only by a timestamp. Training on it undifferentiated would teach a
model the bugs.

The cut points are commit times. Anything logged before the listed commit is an
**artifact, not evidence**:

| Data | Contaminated before | Why |
|---|---|---|
| `tier2_shadow.jsonl` — put/call flip rows | `fbaba02` (~12:0x) | Net call premium was clamped at zero, forcing the ratio to exactly 1.0 for any name with net call selling. It fired "100.0% puts" on all 9 positions every minute. Mathematically incapable of not firing. |
| `tier2_shadow.jsonl` — dark-pool rows | `f6c6d3d` (~11:5x) | Queried the 50 most *recent* prints, not the largest. Read a $1.0M print on NVDA while the day's real activity was $447M — off by 400×, and re-rolling every minute as the window slid. SKHY's direction was inverted. |
| All Tier 2 rows | `e68a86e` (~11:4x) | Before this, Tier 2 threw `float − str` on **every** check since inception. It logged "ACTIVE" at startup and did nothing. Any earlier row is absence, not signal. |
| Barrier/exit labels | `942802c` (~09:5x) | Stops/targets were 1.5×/2.5× ATR — measured same-session touch probability 5.3% and 0.3%. Effectively unreachable, so every label is a time barrier by construction, not by market behaviour. |
| Entry candidate distribution | `3ed29b1` (~12:0x) | DTE was not filtered server-side, so only ~12–16% of each fetch was inside the tradeable window. The candidate mix changes sharply after this commit. |
| Position sizing | `f572bc9` (~11:4x) | `int(target // price)` returned zero above the dollar target, so every stock over ~$750 was structurally excluded regardless of signal. MU was rejected at 90% and 93% confidence purely for this. Pre-fix data has a survivorship hole at high prices. |

**Practical rule:** for supervised work, use rows after `3ed29b1` only, and
treat the whole day as ~3 hours of clean data rather than 6.

---

## Files

| File | Rows | Contents |
|---|---|---|
| `data/features.jsonl` | 474 | Per-candidate feature vectors (55 fields incl. net delta dollars, gate scores, contract greeks). Join to outcomes by `candidate_id`. |
| `data/screened_alerts.jsonl` | — (4.3 MB) | Every alert that passed Phase 1, pre-consolidation. The widest raw record. |
| `data/labels.jsonl` | — | Triple-barrier outcome labels. **All are `0` (time barrier)** — see barrier note above. |
| `data/closed_trades.jsonl` | — | Realised trades with entry/exit/P&L and exit reason. |
| `data/excursions.jsonl` | 9 | MFE/MAE per position in ATR units. |
| `data/tier2_shadow.jsonl` | 1,158 | Tier 2 would-have-exited decisions. **Heavily contaminated — see table.** |
| `data/uw_confirmation_ab.jsonl` | 6 | Options-confirmation A/B pairs from the production bot (shadow). Far too few to use. |
| `data/whale_watchlist.json` | 2,675 | OI state machine per tracked block (PENDING→CONFIRMED→UNWINDING). Includes GOOGL 370C confirming at 29,797 OI from a 2,288 baseline. |
| `data/open_positions.json` | — | Empty at capture; EOD flatten had run. |
| `logs/` | 12 files | Full decision trail. Webhook tokens scrubbed. |

## Known label limitations

- **No stop or target has ever fired in this bot's history**, today included.
  Every exit was EOD flatten (10), bearish flow (8) or rotation (2). The exit
  path is unobserved, so any model trained on exit outcomes is learning the
  time barrier and the bearish-flow rule, nothing more.
- 81 bearish signals were discarded unlabelled by the long-only rule — a
  systematic censoring correlated with signal strength (the discarded set skews
  *high* confidence: SPY 96%, GOOGL 96%, IWM 94%). This is not missing at
  random.
- Win rate 20% on 20 trades carries no information. Do not use it as a target.

## What the day's research established

Six hypotheses backtested with market-adjustment, day-neutralisation, split
guards and non-overlapping windows. **None shows edge.** Reproduce with the
committed scripts rather than trusting this summary:

`uw_block_backtest.py` · `uw_vol_backtest.py` · `uw_flow_backtest.py` ·
`uw_pcflip_backtest.py` · `uw_gates_backtest.py` · `uw_earnings_backtest.py`

Most relevant to modelling: the **technical gates do not predict** (104,924
obs; traded set −0.03% vs skipped +0.01%). Gate confidence is therefore not a
useful feature or target on this evidence, despite being the bot's primary
decision variable.
