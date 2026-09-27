#!/usr/bin/env bash
# Build a real-text corpus for llm_decode_bench.py's --context-file.
#
# WHY THIS EXISTS: the prefill A/B work recorded on 2026-09-27 used a real
# corpus rather than the synthetic padding generator, because qwen3.8-flash-next
# carries a ~26.8 GiB n-gram/PLE table and a repeated-filler prompt cannot
# exercise it (see knowledge/research/2026-09-27-prefill-bench-padding-trap.md).
#
# The corpus actually used for those measurements is deliberately NOT committed:
# it was harvested from BOTH this repo and local-ai-machine, and it contains
# credential-shaped strings (api_key:, password, API_KEY=) from the latter. This
# repo is public. Do not add it.
#
# CONSEQUENCE, stated rather than glossed: the exact bytes behind the 2026-09-27
# numbers cannot be regenerated from this repo. The sorted file list below makes
# a DETERMINISTIC equivalent from this repo alone; re-running an old A/B on it
# will give slightly different absolute rates, though the comparisons that
# matter (same corpus, two builds) hold regardless.
#
# usage: scripts/build_bench_corpus.sh [output-path]
set -euo pipefail
OUT="${1:-/tmp/repo-corpus.txt}"
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
: > "$OUT"
# Sorted, so the output is reproducible. This repo only.
find "$ROOT" -type f \
  \( -name '*.py' -o -name '*.md' -o -name '*.nix' -o -name '*.sh' -o -name '*.yaml' \) \
  -not -path '*/.git/*' -print0 | sort -z | xargs -0 cat >> "$OUT"
echo "wrote $OUT ($(wc -c < "$OUT") bytes)"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
