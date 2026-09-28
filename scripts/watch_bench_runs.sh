#!/usr/bin/env bash
# Completion watcher for bench runs 154-159. Exits the moment every run is
# terminal, which is what wakes the agent (job completion -> notification).
# Not a substitute for the operator's timers - a fallback so progress does not
# silently stall while the machine is unattended.
set -u
IDS="161 162 163"
MAX=$((7*3600)); t0=$(date +%s); last_report=0
status_of() { curl -s --max-time 8 "http://127.0.0.1:8092/runs/$1" \
  | python3 -c "import json,sys
try: print(json.load(sys.stdin).get('status','?'))
except Exception: print('unreachable')" 2>/dev/null; }
while :; do
  pend=0; line=""
  for id in $IDS; do
    s=$(status_of "$id"); line="$line $id=$s"
    case "$s" in queued|running|unreachable|'') pend=$((pend+1));; esac
  done
  el=$(( $(date +%s) - t0 ))
  if [ $(( el - last_report )) -ge 900 ]; then
    echo "[$(date -u +%H:%M:%SZ)] elapsed $((el/60))min:$line"; last_report=$el
  fi
  if [ "$pend" -eq 0 ]; then echo "ALL TERMINAL after $((el/60))min:$line"; break; fi
  if [ "$el" -ge "$MAX" ]; then echo "WATCHER TIMEOUT after $((el/60))min:$line"; break; fi
  sleep 60
done
echo "--- final per-run detail ---"
for id in $IDS; do
  curl -s --max-time 8 "http://127.0.0.1:8092/runs/$id" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for b,v in d.get('per_build',{}).items():
    print(f\"  run {d['id']:<4} {d['status']:<8} {b[:52]:<52} {v.get('status'):<8} {v.get('raw_json') or v.get('error') or ''}\")
" 2>/dev/null
done
