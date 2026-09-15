#!/bin/bash
# Dense one-screen status for the live session. Read-only: greps logs and the
# position file, touches no API and places no orders.
cd /Users/ramayalala/trading_bot_uw || exit 1
L=$(ls -t logs/uw_bot_2026*.log 2>/dev/null | head -1)
[ -z "$L" ] && { echo "no log found"; exit 1; }

echo "═══ $(date '+%H:%M %Z')  ·  $(basename "$L") ═══"
PID=$(pgrep -f "unusual_whales_bot/uw_bot.py" | head -1)
echo "bot: ${PID:-NOT RUNNING}   cycles: $(grep -c 'Cycle complete' "$L")"

# Live orders actually sent
echo "--- orders"
ORD=$(grep -c "🚀 LIVE order" "$L")
echo "  live orders sent: $ORD"
[ "$ORD" -gt 0 ] && grep "🚀 LIVE order" "$L" | tail -5 | sed 's/^/    /' | cut -c1-120

# Entries / exits
echo "--- entries & exits"
grep -E "📥 ENTRY|🎯|🛑|🌆|TARGET HIT|STOP HIT|EOD" "$L" | tail -6 | sed 's/^/    /' | cut -c1-120

# Open positions
echo "--- open positions"
python3 - <<'PY'
import json
try:
    d = json.load(open("open_positions.json"))
    p = d if isinstance(d, list) else d.get("positions", d)
    ks = list(p) if isinstance(p, dict) else p
    print(f"    {len(ks)} open")
    for k in (ks[:6] if isinstance(ks, list) else list(ks)[:6]):
        v = p[k] if isinstance(p, dict) else k
        if isinstance(v, dict):
            print(f"      {v.get('symbol','?'):<6} qty {v.get('quantity','?')} "
                  f"@ {v.get('entry_price','?')}")
except Exception as e:
    print(f"    (unreadable: {e})")
PY

# Today's realised P&L
echo "--- realised P&L today"
python3 - <<'PY'
import json, datetime
today = datetime.date.today().isoformat()
try:
    r = [json.loads(l) for l in open("closed_trades.jsonl") if l.strip()]
    t = [x for x in r if str(x.get("exit_time", ""))[:10] == today and x.get("pnl") is not None]
    if not t:
        print("    no closed trades yet today")
    else:
        p = [float(x["pnl"]) for x in t]
        w = sum(1 for x in p if x > 0)
        print(f"    {len(p)} closed   P&L ${sum(p):+.2f}   wins {w}/{len(p)}")
        import collections
        for k, n in collections.Counter(str(x.get("exit_reason")) for x in t).most_common():
            print(f"      {k:<28}{n}")
except Exception as e:
    print(f"    (unreadable: {e})")
PY

# Refusals and anything loud
echo "--- refusals / errors"
grep -oE "index_not_tradeable|cooldown|broker_only_position|no_price" "$L" | sort | uniq -c | sed 's/^/    /' | head -5
E=$(grep -cE "🚨|ERROR" "$L")
echo "    errors/alerts: $E"
[ "$E" -gt 0 ] && grep -E "🚨|ERROR" "$L" | tail -3 | sed 's/^/      /' | cut -c1-120
exit 0
