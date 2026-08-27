---
id: 2026-07-23-phase3-optimization-aiter-eager-batching
date: 2026-07-23
source: "README.md (Decision Log — 2026-07-23 later still: Phase 3 optimization — AITER tested, doesn't work)"
tags: [vllm, aiter, rocm, awq, config-default, benchmark]
status: active
---

# Phase 3 optimization results: AITER rejected, non-enforce-eager AWQ adopted, larger chunked-prefill rejected

**Decision 1 — AITER stays off.** Tested enabling `VLLM_ROCM_USE_AITER=1` (default False,
confirmed via vLLM's own `envs.py` source, meaning AITER had been off by default for every
model benchmarked so far). Result: immediate engine crash
(`UnicodeDecodeError` while registering an AITER torch op), not a slow start or benchmark
artifact — a fundamental incompatibility between this AITER build and this toolbox
image/hardware combination, for a plain bf16 MoE model with no quantization involved.
Confirmed universal across 3 distinct architectures (Qwen dense-MoE, Qwen GPTQ, Gemma) —
all crash identically, just a different byte offset each time. **Decided: AITER being off
(the default) is correct for this hardware, not an untested opportunity being left on the
table.** Not worth revisiting without a different toolbox/AITER build.

**Decision 2 — adopt non-`enforce-eager` for the 122B AWQ tier.** Full writeup in
`knowledge/decisions/2026-07-23-adopt-non-eager-awq-122b.md` — captured here only as a
summary since it was part of the same Phase 3 pass: tested without `--enforce-eager`,
found a real but marginal improvement (~1-9% across metrics, no regression), and Chris
decided to adopt it as the standing default for future swap-ins of this model (still
requires `VLLM_USE_TRITON_AWQ=1`, unrelated to eager mode). Accepted tradeoff: slower cold
start (~410s vs ~350s).

**Decision 3 — do not adopt a larger `--max-num-batched-tokens`.** Tested 16384 (double
the default 8192) against the c8 baseline for the 35B-A3B primary: -9% throughput, TTFT
mean +65% (worse across the board). Confirmed as a universal regression across all 6
models tested (throughput flat-to-worse in every case, TTFT consistently and
substantially worse, +13% to +98%). **Decided: keep the default (8192) everywhere.** If
chunked-prefill tuning is revisited later, try a smaller value than the default instead,
since larger clearly hurts across the board.

**Item (d), MTP speculative decoding for the Qwen3-Next family, was not attempted this
session** — unconfirmed on ROCm at the time, same architecture family that broke outright
on FP8 elsewhere, treated as a real experiment for a dedicated session rather than a quick
test.
