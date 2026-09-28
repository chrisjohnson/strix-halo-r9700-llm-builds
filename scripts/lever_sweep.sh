#!/usr/bin/env bash
# Run the agentic replay AND a 64k PP/TG point against each build in turn, and
# summarise. Built for the flash-next tuning-lever sweep: one build per lever, so
# the comparison is attributable.
#
# Each build is brought up exclusively through modelctl, which waits for health and
# then primes - so no run measures a cold model.
#
# usage: scripts/lever_sweep.sh <build-id> [<build-id> ...]
set -uo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="${AGENTIC_PY:-$HOME/scratch/tuning/venv/bin/python}"
CTX="${SWEEP_CTX:-65536}"
OUT="${AGENTIC_OUT:-$HOME/scratch/tuning}"
[ "$#" -ge 1 ] || { echo "usage: $0 <build-id> [...]" >&2; exit 2; }

for id in "$@"; do
  f="$REPO/builds/$id/docker-compose.yaml"
  [ -f "$f" ] || { echo "skip $id: no compose"; continue; }
  port="$(grep -oE '127\.0\.0\.1:[0-9]+' "$f" | head -1 | cut -d: -f2)"
  echo "=================== $id (:$port) ==================="
  ( cd "$REPO" && sudo -n "$REPO/modelctl" up --exclusive "$id" ) > "$OUT/sweep_up_$port.log" 2>&1
  echo "  bring-up exit=$? (log: $OUT/sweep_up_$port.log)"
  grep -E 'primed|healthy|warning' "$OUT/sweep_up_$port.log" | tail -2 | sed 's/^/    /'
  for i in $(seq 1 40); do curl -sf -o /dev/null -m 3 "http://127.0.0.1:$port/health" && break; sleep 5; done
  echo "  --- PP/TG at $((${CTX}/1024))k ---"
  "$REPO/scripts/pp_tg_at_context.sh" "$port" "$CTX" "$(echo "$id" | sed 's/.*budget-//;s/-strixhalo.*//')"
  echo "  --- agentic replay ---"
  "$PY" "$REPO/llm-inference-bench/agentic_replay.py" --port "$port" --turns "${SWEEP_TURNS:-12}" \
       --compact-at 8 --label "$(echo "$id" | sed 's/.*budget-//;s/-strixhalo.*//')" 2>&1 | tail -16
done

echo
echo "=================== SWEEP SUMMARY ==================="
"$PY" - <<PY
import json, glob, os
rows=[]
for f in sorted(glob.glob("$OUT/pptg_*_${CTX}.json")):
    port=os.path.basename(f).split("_")[1]
    a=os.path.join("$OUT", f"agentic_{port}.json")
    if not os.path.exists(a): continue
    d=json.load(open(f)); pre=(d.get("prefill") or {}).get("$CTX")
    dec=[r for r in d.get("results",[]) if r.get("context_tokens")==$CTX and r.get("concurrency")==1]
    ag=json.load(open(a)); rs=ag["rows"]
    hot=[r for r in rs if not r["compaction"] and r["turn"]>1]
    comp=[r for r in rs if r["compaction"]]
    rows.append(dict(label=ag.get("label") or port, port=port,
        pp=pre["tok_per_sec"] if pre else 0,
        tg=(dec[0].get("per_request_avg_tps") if dec else 0) or 0,
        hit=sum(r["cached_tokens"]/r["prompt_tokens"]*100 for r in hot)/len(hot) if hot else 0,
        wall=sum(r["wall_s"] for r in hot)/len(hot) if hot else 0,
        comp=comp[0]["wall_s"] if comp else 0))
print(f"  {'lever':<12} {'PP@64k':>8} {'TG@64k':>8} {'cache hit':>10} {'wall/turn':>10} {'compaction':>11}")
for r in sorted(rows, key=lambda r:-r['pp']):
    print(f"  {r['label'][:12]:<12} {r['pp']:>8.0f} {r['tg']:>8.1f} {r['hit']:>9.1f}% {r['wall']:>9.2f}s {r['comp']:>10.1f}s")
PY
