---
id: 2026-07-23-adopt-non-eager-awq-122b
date: 2026-07-23
source: "README.md (Decision Log — 2026-07-23 later still, Phase 3 optimization)"
tags: [vllm, awq, config-default]
status: active
---

# Adopt non-`enforce-eager` as the standing default for the 122B AWQ tier

**Decision**: when swapping in `Qwen3.5-122B-A10B-AWQ-4bit`, do not pass
`--enforce-eager`. `VLLM_USE_TRITON_AWQ=1` is still required (a separate, real AWQ-kernel
dependency, unrelated to eager mode).

**Why**: benchmarked head-to-head against the enforce-eager baseline. Removing
`enforce-eager` improved every metric by 1-9% (e.g. c8 output tok/s 16.05 -> 16.28, c1
7.87 -> 8.14) with no regression anywhere. The original hypothesis — that `enforce-eager`
was the main driver of this model's poor concurrency scaling — turned out to be only
marginally true; the model's underlying slowness at this size/hardware combination is the
bigger factor, not the eager-mode flag.

**Alternatives considered**: keeping `enforce-eager` (the prior default, adopted earlier
without this comparison having been run, believed at the time to be required for the AWQ
kernel path). Rejected once the comparison showed no benefit and a real, if small, cost.

**Tradeoff accepted**: slower cold start (~410s vs ~350s) from CUDA graph capture at
startup — accepted since this model stays loaded once served, and swap-in frequency
during benchmarking was judged a lesser cost than steady-state throughput.

**Practical implication**: this model has no compose entry or standing serve script of its
own — it's only ever swapped in ad hoc via `swap_model_start.sh` with
`SWAP_ENV_VARS='VLLM_USE_TRITON_AWQ=1'` — so "adopting the default" means: going forward,
do not pass `--enforce-eager` when swapping this model in.

**Decided by**: Chris, 2026-07-23.
