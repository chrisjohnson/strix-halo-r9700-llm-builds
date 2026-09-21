#!/usr/bin/env bash
# M-149: ad hoc wall-clock-per-image timing harness for this build.
# llm-inference-bench's orchestrator is tokens/sec-only and has no
# images/sec concept, so this build's benchmarking doesn't go through it
# (see build.yaml's notes) — this script times real generation calls
# against the build's own port directly, one run per (steps, resolution)
# combination, and writes raw JSON next to itself the same "raw,
# untainted" way llm-inference-bench writes its own results.
#
# Uses the A1111-compatible /sdapi/v1/txt2img route, NOT
# /v1/images/generations: confirmed via a real run that the
# OpenAI-compatible route silently drops an unrecognized `steps` field
# (OpenAI's own /v1/images/generations schema has no such parameter at
# all - prompt/n/size/output_format/output_compression only), so two
# "20 vs 40 steps" calls against it came back statistically identical
# (267.5s vs 264.4s) - both actually ran at the server's own default.
# This means litellm's role (which calls the OpenAI-compatible route)
# has NO way to control step count per request either - see build.yaml.
#
# Run from the box (build must already be up first, e.g. `modelctl up
# qwen-image-2.1--stable-diffusion-cpp-vulkan-radv-strix-apu-v1`).
# Optional $1: override the port (for a sibling build's own copy of this
# script pointed at its own port - see e.g. v2's benchmarks/ directory).
set -euo pipefail

PORT="${1:-8200}"
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PROMPT="a lovely cat holding a sign that says 'qwen-image-2.1'"

declare -a RUNS=(
  "4 1024x1024"
  "20 1024x1024"
)

results="[]"
for run in "${RUNS[@]}"; do
  steps="${run% *}"
  size="${run#* }"
  width="${size%x*}"
  height="${size#*x}"
  echo "== steps=$steps size=$size ==" >&2
  start=$(date +%s.%N)
  http_code=$(curl -s -o "$OUT_DIR/${STAMP}-steps${steps}-${size}.json" -w '%{http_code}' \
    -X POST "http://127.0.0.1:${PORT}/sdapi/v1/txt2img" \
    -H 'Content-Type: application/json' \
    -d "{\"prompt\": \"${PROMPT}\", \"steps\": ${steps}, \"width\": ${width}, \"height\": ${height}}")
  end=$(date +%s.%N)
  elapsed=$(python3 -c "print($end - $start)")
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
