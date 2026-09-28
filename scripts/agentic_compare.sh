#!/usr/bin/env bash
# Run the agentic replay against several builds, one at a time, and summarise.
#
# The plan's section 2 metric: end-to-end latency of a turn in a GROWING
# conversation, with cache-hit fraction and compaction cost. This is the
# comparison that should rank candidate engines, rather than headline prefill.
#
# Each build is brought up exclusively (which stops anything else on the same
# GPU) via modelctl, so `up` waits for health and primes before measuring.
#
# usage: scripts/agentic_compare.sh <build-id> [<build-id> ...]
set -uo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="${AGENTIC_PY:-$HOME/scratch/tuning/venv/bin/python}"
TURNS="${AGENTIC_TURNS:-12}"
OUT="${AGENTIC_OUT:-$HOME/scratch/tuning}"
[ "$#" -ge 1 ] || { echo "usage: $0 <build-id> [...]" >&2; exit 2; }

declare -a done_ids=()
for id in "$@"; do
  f="$REPO/builds/$id/docker-compose.yaml"
  if [ ! -f "$f" ]; then echo "skip $id: no compose file" >&2; continue; fi
  port="$(grep -oE '127\.0\.0\.1:[0-9]+' "$f" | head -1 | cut -d: -f2)"
  echo "=================== $id (:$port) ==================="
  # Absolute path: the sudoers rule names it, and it works from any cwd.
  # Output goes to a log rather than through a filter -- an earlier version piped
  # this through `grep -E 'primed|healthy|warning'`, which DELETED the error line
  # ("sudo: ./modelctl: command not found") and left the script silently waiting
  # 200 s for a port that was never going to open. Never filter a bring-up.
  ( cd "$REPO" && sudo -n "$REPO/modelctl" up --exclusive "$id" ) > "$OUT/bringup_$port.log" 2>&1
  echo "  bring-up exit=$? (log: $OUT/bringup_$port.log)"
  grep -E 'primed|healthy|warning|error|refus' "$OUT/bringup_$port.log" | tail -3 | sed 's/^/    /' 
  for i in $(seq 1 40); do
    curl -sf -o /dev/null -m 3 "http://127.0.0.1:$port/health" && break
    sleep 5
  done
  "$PY" "$REPO/llm-inference-bench/agentic_replay.py" --port "$port" --turns "$TURNS" \
       --compact-at "${AGENTIC_COMPACT_AT:-8}" --label "$id" 2>&1 | tail -n +2
  [ -f "$OUT/agentic_$port.json" ] && cp "$OUT/agentic_$port.json" "$OUT/agentic_$(echo "$id" | tr '/' '_').json"
  done_ids+=("$id")
done

echo
echo "=================== SUMMARY ==================="
"$PY" - <<PY
import json, glob, os
rows=[]
for f in sorted(glob.glob("$OUT/agentic_*.json")):
    try: d=json.load(open(f))
    except Exception: continue
    rs=d["rows"]; hot=[r for r in rs if not r["compaction"] and r["turn"]>1]
    comp=[r for r in rs if r["compaction"]]
    if not hot: continue
    hits=[r["cached_tokens"]/(r["prompt_tokens"]+r["cached_tokens"])*100 for r in hot]
    walls=[r["wall_s"] for r in hot]
    rates=[r["prompt_tokens"]/r["prefill_s"] for r in hot if r["prefill_s"]]
    rows.append(dict(label=d.get("label") or os.path.basename(f),
                     hit=sum(hits)/len(hits), wall=sum(walls)/len(walls),
                     rate=sum(rates)/len(rates),
                     comp=(comp[0]["wall_s"] if comp else None),
                     comp_tok=((comp[0]["prompt_tokens"]+comp[0]["cached_tokens"]) if comp else None)))
seen=set(); uniq=[]
for r in rows:
    if r["label"] in seen: continue
    seen.add(r["label"]); uniq.append(r)
print(f"  {'build':<58} {'cache hit':>9} {'wall/turn':>10} {'incr tok/s':>11} {'compaction':>11}")
for r in sorted(uniq, key=lambda r:-r["hit"]):
    c=f"{r['comp']:.1f}s @{r['comp_tok']:,}" if r["comp"] else "--"
    print(f"  {r['label'][:58]:<58} {r['hit']:>8.1f}% {r['wall']:>9.2f}s {r['rate']:>11.0f} {c:>11}")
PY
