---
id: 2026-10-05-qwen4exp-mtp-vision-oom
date: 2026-10-05
source: "M-158/M-159 (local-ai-machine board): two real production crashes on flash-next
  (big-moe) during Chris's own long-horizon vision usage, root-caused via an instrumented
  debug build and live crash reproduction"
tags: [flash-next, qwen4exp, vision, mtp, qsa, oom, ggml, crash, m159]
status: active
---

# flash-next OOM-crashes on vision + MTP once an image stays in a long context

Two real crashes on the standing `big-moe` build (2026-10-05, ~75 minutes apart, same
conversation): `ggml_backend_cuda_buffer_type_alloc_buffer: ... cudaMalloc failed: out of
memory`, requesting 19.8 GiB the first time and 79.4 GiB the second, both inside
`ggml_gallocr_alloc_graph` during ordinary `llama_context::decode` (not the explicit
image-decode path) on the TARGET model's own forward pass. local-ai-machine board cards
M-158 (symptom, first crash) and M-159 (root-cause + fix attempt) track this; this doc is
the portable, engine-level writeup.

## Root cause, confirmed via live instrumented reproduction (not inferred)

This model's QSA (sparse attention) indexer has two selection paths:

- **Scalar/compact** (cheap): operates at block granularity via
  `qwen4exp_select_complete_blocks`, never materializes a per-cell tensor.
- **Non-scalar** (expensive): `build_qsa_top_k`'s fallback branch (qwen4exp.cpp, around the
  `expanded`/`mask` tensors) expands per-block scores to per-CELL granularity - an
  `[n_kv, n_query, n_stream]` f32 tensor, twice (once for the score expansion, once for the
  mask cast) - before reducing to the final top-`width` selection via `ggml_top_k`.

Which path runs is decided by `llama_memory_hybrid_idx_context::qsa_scalar_visibility()`
(`llama-memory-hybrid-idx.cpp`). It scans every cell in the KV cache and returns false if
**any** cell is a genuine 2D-positioned (M-RoPE image) cell - correctly, since the cheap
path's assumptions don't hold with real 2D cells in the candidate pool. At this model's
native 262144-token context, an image's cells never get evicted. **So once any image enters
a long conversation, the expensive path runs for every subsequent request in that
conversation, permanently**, confirmed live via added instrumentation
(`[DBG scalar_vis] FALSE at is_pos_2d cell-scan j=<the image's own cell>`).

The expensive path's cost is `n_kv × ubatch_size` per sparse layer (12 of 48 layers have
`compress_ratio=4`), and **ggml's graph allocator does not reuse this memory across either
the chunked strip-iterations or the 12 layers** - confirmed by a failed fix attempt (below).
At the second crash's depth (`n_kv≈162304`, `-ub 8192`), that's enough to exceed 79 GiB.

## What was tried and ruled out

**Rechunking the strip loop (fix attempt 1, reverted).** `qwen4exp_query_strip()` already
capped the per-iteration chunk at 512 queries; reducing it further (budget-based, down to
~17-25 at this `n_kv`) shrank each `expanded`/`mask` tensor 20x (317 MiB → 15.5 MiB) -
confirmed via instrumentation - but **the crash's total requested buffer size was
byte-identical before and after** (83,259,472,000 bytes both times). This is the
proof that the allocator isn't reusing memory across iterations/layers here: total work is
fixed at `n_kv × n_tps` regardless of how finely it's chunked within one graph build.

**A proper restructuring was identified but not attempted.** The existing
`[QSA_SCORE_BOUNDS]` mechanism (`qwen4exp_score_key_limits`, a causal-prefix argument:
"every block visible to any query in a strip lies in the first (max_query_position+1)/ratio
columns") already does something like the right bound - but it's gated behind `compact`
(scalar) mode, via `qsa_position_prefix()` which itself requires `qsa_scalar_visibility()`.
A genuinely general fix would restructure `build_qsa_top_k`'s non-scalar branch into a
two-stage selection: cheap block-level top-k on the already-small `score` tensor
(`[n_blocks, n_idx_h, n_query]`, no `n_kv` dimension) to narrow to a few hundred candidate
blocks, THEN expand only those to per-cell for the final fine-grained top-k - cutting the
expansion from `n_kv` (hundreds of thousands) down to roughly `width/ratio` blocks
(~500ish). This is very likely the right engineering fix, but it touches what the model
actually attends to, and wasn't attempted without real output-correctness validation
infrastructure (comparing against the unpatched model on non-crashing prompts) that wasn't
available in the time budget. Flagged here for whoever picks this up next, including
pwilkin upstream if this gets reported there - nothing like it exists yet in either
`pwilkin/llama.cpp` (confirmed at the tip of `strix-halo` branch, `ahead_by: 0, behind_by: 0`
against our pin) or upstream `ggml-org/llama.cpp` (issue #22867, "MTP + Vision causes slot
position corruption and OOM", still open).

## What was validated: `-ub` reduction

Since the actual lever is `n_tps` (the ubatch size) and not the chunking, and `-ub` is a
plain launch flag (no code patch needed), reducing it directly reduces the crash's total
size. Validated empirically against the exact repro that crashed in production, rebuilt
step by step up to 98% of the model's full 262144-token context:

| `-ub` | outcome | depth tested |
|---|---|---|
| 8192 (current standing) | crashes (confirmed twice in production) | 158,961 / 167,212 |
| 2048 | **survives**, no crash | up to 256,691 (98% of max 262144) |

Cost: real prefill speed, measured on the ~153k-token portion of the repro: 8192 took
~220s, 2048 took ~314s (≈43% slower). This is in addition to the ~6% already paid for the
16384→8192 step in the standing build's own history (see that build's `build.yaml`).

## Why this matters for anyone reconsidering `-ub` on this build

`-ub` was tuned down once already (16384→8192, M-157) purely for GTT headroom, unrelated to
this bug - that tuning pass never exercised vision at depth, so it couldn't have caught
this. Any future `-ub` increase on a vision-enabled build should be re-validated against
this exact failure mode (an image early in a long, deep conversation), not just against
plain-text throughput, since the two failure surfaces are independent and this one doesn't
show up until real depth.
