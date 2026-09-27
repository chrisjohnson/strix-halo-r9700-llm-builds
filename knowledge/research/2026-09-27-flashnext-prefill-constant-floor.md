---
id: 2026-09-27-flashnext-prefill-constant-floor
date: 2026-09-27
source: direct measurement on local-ai-machine against the running qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v1 build, via llm_decode_bench.py --prefill-contexts 1024,2048,4096,8192
tags: [qwen3.8-flash-next, prefill, throughput, constant-cost, ple, engram, strix-halo, benchmark]
status: active
---

# There is a large constant per-token prefill cost: ~2.58 ms/token before context costs anything

## Finding

Prefill at small contexts, real-corpus text, single stream, server-reported timings:

| requested | actual tokens | tok/s | ms/token | distinct 3-grams |
|---|---|---|---|---|
| 1k | 1,438 | 339 | 2.950 | 556 |
| 2k | 2,409 | 350 | 2.857 | 1,197 |
| 4k | 5,073 | 380 | 2.632 | 2,079 |
| 8k | 9,400 | 376 | 2.660 | 4,288 |

Fitting `ms/token = C + F/tokens` gives **C = 2.576 ms/token** (the context-independent
floor) and **F = 562 ms** (fixed per-request overhead).

At 250,867 tokens this build runs at 141.8 tok/s = 7.05 ms/token, so **the constant floor is
~37% of the per-token cost at full context** — and ~87% of it at 1.4k tokens. In other words
the model spends 2.58 ms on every single token before context length contributes anything,
and that is an upper bound on what *any* context-independent optimisation (parallel pread
included) could ever recover.

## Why this matters: it changes the PR #29030 recommendation

The 65% falloff from 8k to 251k is context-driven and is *not* the n-gram/PLE path — that
conclusion rests on three independent lines and still stands. But "the PLE path is not
responsible for the falloff" is not the same claim as "the PLE path costs nothing", and the
measurement above is the difference between those two claims:

- The PLE tensor is **mmap-backed on CPU** and this build's own local patch deliberately
  *disables* whole-file prefetch for it (`ml.init_mappings(false, ...)`, "whole-file prefetch
  defeats that arrangement and thrashes memory on UMA" — see
  `docker/qwen4exp-strix-halo-mtp/llama-cpp-qwen38-per-buffer-mmap.patch`). Its rows are
  demand-faulted.
- The gather is **16 rows per token** (16 heads x one ~160-element row, per the model's
  `ple.ngram_size=3`, `ple.heads_per_ngram=8`, and the DGX Spark thread's independent
  description of the same tensor). That count is fixed per *token*, not per distinct n-gram —
  which is exactly why realistic text, with 3x more distinct trigrams, is not slower
  (see the padding-trap note).
- `--lazy-mode on-direct` (PR #29030/#28136) exists precisely to issue those reads in
  parallel instead of one at a time.

So the port targets a **constant per-token cost**, not the falloff. Whether it is worth
building therefore depends entirely on how much of the 2.58 ms floor is that gather — and
**that is not measured.** 16 rows in 2.58 ms would be 161 us per row if fully serialised,
which is in the plausible range for cold random reads on this box's storage, but the floor
also contains the 36 SSM layers' state updates, MoE routing, the context-independent part of
the 12 attention layers' projections, and KV writes. Compute alone should be a fraction of a
millisecond; the rest is unaccounted.

## How to settle it (needs docker access)

The floor's composition is separable with launch flags on a throwaway instance, all of which
are cheap because the contexts involved are tiny:

- `--tensor-read-lazy off` (or `--lazy-mode off`) — makes the table resident instead of
  demand-faulted. If the floor collapses, the gather is the floor. Costs RAM and will not fit
  alongside the full context, but at 1k-8k tokens it is a clean test.
- `--load-mode dio` — direct I/O for bulk weights, table left on the mmap path (the Spark
  thread's own suggestion).
- prefill at 1k/2k/4k/8k with the table's gather effectively disabled by any means the build
  exposes.

Until that runs, the honest position is: **the port addresses a real, always-present cost of
unknown size, and it is not the cause of the falloff.** It should be re-prioritised on the
strength of that distinction rather than dismissed.

## Caveats

- Four points, n=1 each, 1,438-9,400 tokens. The 4k and 8k points are 2.632 and 2.660
  ms/token — non-monotonic by 1%, which is the noise level. The fitted floor should be read
  as 2.5-2.7 ms/token, not 2.576 exactly.
- The fit assumes the fixed overhead is purely per-request. Some of what the fit calls
  "constant floor" could be a second-order context term that is small but not zero over
  1.4k-9.4k tokens; that would make the floor an overestimate.
- Measured with dirk resident on the R9700 (its own VRAM, ~4.8 MB host RSS), so the confound
  is small but not zero.
- Appendix-scale result: the model's own compute should be well under 1 ms/token, so most of
  the floor is *not* arithmetic. That is an argument that something I/O- or
  dispatch-shaped dominates, not a measurement of which.
