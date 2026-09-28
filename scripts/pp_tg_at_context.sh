#!/usr/bin/env bash
# Measure prefill (PP) and generation (TG) at ONE context length, for one running build.
#
# Written for the "how far have we improved over baseline" question: the A/B ladders
# went to 32k and the standard bench uses a synthetic-filled prompt, so neither
# answers "PP and TG at 64k on real text". This runs one real-corpus prompt of the
# requested size through llm_decode_bench.py and prints the server's own timings.
#
# usage: scripts/pp_tg_at_context.sh <port> <context-tokens> [label]
set -uo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="${AGENTIC_PY:-$HOME/scratch/tuning/venv/bin/python}"
PORT="${1:?usage: $0 <port> <context-tokens> [label]}"
CTX="${2:?usage: $0 <context-tokens>}"
LABEL="${3:-port $PORT}"
CORPUS="${CORPUS:-$HOME/scratch/tuning/corpus.txt}"
OUT="$HOME/scratch/tuning/pptg_${PORT}_${CTX}.json"

[ -f "$CORPUS" ] || { echo "no corpus at $CORPUS" >&2; exit 1; }
"$PY" "$REPO/llm-inference-bench/llm_decode_bench.py" \
  --host 127.0.0.1 --port "$PORT" --model "$LABEL" --engine sglang \
  --contexts "$CTX" --concurrency 1 --duration "${TG_SECONDS:-20}" --max-tokens "${TG_TOKENS:-512}" \
  --prefill-contexts "$CTX" --prefill-repeats 1 --padding-seed bench \
  --context-file "$CORPUS" --output "$OUT" >/dev/null 2>&1

"$PY" - "$OUT" "$LABEL" "$CTX" <<'PYEOF'
import json, sys
out, label, ctx = sys.argv[1], sys.argv[2], int(sys.argv[3])
d = json.load(open(out))
pre = (d.get("prefill") or {}).get(str(ctx))
dec = [r for r in d.get("results", []) if r.get("context_tokens") == ctx and r.get("concurrency") == 1]
pt = pre.get("tok_per_sec") if pre else None
pn = pre.get("prompt_tokens") if pre else None
tg = dec[0].get("per_request_avg_tps") if dec else None
agg = dec[0].get("aggregate_tps") if dec else None
print(f"  {label:<44} PP {pt:>7.0f} tok/s ({pn:,} tok prompt)   TG {tg:>6.1f} tok/s (per-request, agg {agg:.1f})"
      if pt and tg else f"  {label:<44} PP {pt}  TG {tg}")
PYEOF
