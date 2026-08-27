---
id: 2026-07-23-swap-benchmark-script-and-firewall-followup
date: 2026-07-23
source: "README.md (Decision Log — 2026-07-23: Phase 1 speed-benchmarking, swap-benchmark script, NPU/hybrid research)"
tags: [vllm, benchmark, tooling, script]
status: active
---

# New reusable tool: speed_benchmark_swap.sh, plus real bug fixes found using it

**Decided**: build `scripts/speed_benchmark_swap.sh` to automate the swap-in benchmark
pattern used manually for the GPTQ-80B and 122B-AWQ tiers — stops
`vllm-primary`/`vllm-judge`, starts the model under test alone on port 8000 at
`--gpu-memory-utilization 0.90`, waits for `/health`, runs `vllm bench serve` at
concurrency 1 (2048in/512out, 20 prompts) and concurrency 8 (2048in/256out, 100 prompts),
copies both result JSONs off-box, tears the temp container down, restores the standard
compose stack.

**Why**: manual swap-in benchmarking for each new model tier was repetitive and
error-prone; a reusable script standardizes the procedure and reduces the chance of
skipping a teardown/restore step.

**Real bug found and fixed using it**: the script's `vllm bench serve` invocation was
missing `--tokenizer /models/<dir>` — without it, the benchmark client tries to resolve
the served name as an HF Hub repo ID for tokenizer loading and fails outright. This looked
like "low GPU activity, model barely using memory" from the outside (server loaded fine
and sat idle since no requests ever arrived) — not an optimization opportunity, just a
broken client invocation.

**Second real bug found and fixed mid-run**: no tolerance for a known benchmark-client
segfault-on-exit (same crash-on-cleanup behavior seen with the 122B model earlier) —
under `set -e`, the non-zero exit killed the script immediately after a benchmark's
results printed, skipping teardown and stack restoration. Production was down for a few
minutes before this was caught and fixed manually, then the script was updated to
tolerate the exit-code crash with `|| true` and instead verify success by checking the
result JSON exists inside the container.

**Related decision — firewall gap real fix (see also the 2026-07-22 audit decision)**:
the earlier `filterForward`/`extraForwardRules` fix never actually protected published
ports — see `2026-07-23-firewall-loopback-binding-fix.md` for the complete story and real
fix (loopback binding).
