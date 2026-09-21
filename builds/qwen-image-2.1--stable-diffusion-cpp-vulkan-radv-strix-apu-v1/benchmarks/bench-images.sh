#!/usr/bin/env bash
# M-149: ad hoc wall-clock-per-image timing harness for this build.
# llm-inference-bench's orchestrator is tokens/sec-only and has no
# images/sec concept, so this build's benchmarking doesn't go through it
# (see build.yaml's notes) — this script times real /v1/images/generations
# calls against the build's own port directly, one run per (steps,
# resolution) combination, and writes raw JSON next to itself the same
# "raw, untainted" way llm-inference-bench writes its own results.
#
# Run from the box (build must already be up: `modelctl up
# qwen-image-2.1--stable-diffusion-cpp-vulkan-radv-strix-apu-v1`).
set -euo pipefail

PORT=8200
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PROMPT="a lovely cat holding a sign that says 'qwen-image-2.1'"

declare -a RUNS=(
  "20 1024x1024"
  "40 1024x1024"
)

results="[]"
for run in "${RUNS[@]}"; do
  steps="${run% *}"
  size="${run#* }"
  echo "== steps=$steps size=$size ==" >&2
  start=$(date +%s.%N)
  http_code=$(curl -s -o "$OUT_DIR/${STAMP}-steps${steps}-${size}.png.b64" -w '%{http_code}' \
    -X POST "http://127.0.0.1:${PORT}/v1/images/generations" \
    -H 'Content-Type: application/json' \
    -d "{\"prompt\": \"${PROMPT}\", \"size\": \"${size}\", \"n\": 1, \"steps\": ${steps}}")
  end=$(date +%s.%N)
  elapsed=$(echo "$end - $start" | bc)
  echo "  http=$http_code elapsed=${elapsed}s" >&2
  results=$(echo "$results" | python3 -c "
import json, sys
r = json.load(sys.stdin)
r.append({'steps': $steps, 'size': '$size', 'http_code': '$http_code', 'elapsed_sec': $elapsed})
print(json.dumps(r))
")
done

echo "$results" | python3 -m json.tool > "$OUT_DIR/${STAMP}.json"
echo "Wrote $OUT_DIR/${STAMP}.json" >&2
cat "$OUT_DIR/${STAMP}.json"
