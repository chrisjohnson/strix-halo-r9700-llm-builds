---
id: 2026-09-27-flashnext-incremental-prefill-and-prompt-cache
date: 2026-09-27
source: direct measurement on local-ai-machine against the running qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v1 build, /v1/chat/completions with cache_prompt true
tags: [qwen3.8-flash-next, prefill, prompt-cache, cache-ram, agentic, latency, kv-cache, strix-halo]
status: active
---

# The agentic loop does not pay a full-context prefill per turn: 185s cold, 15.8s to grow

## Finding

Measured against the running flash-next build (default `--cache-ram`, i.e. 8192 MiB, which
this build does not override), a 55k-token prompt sent three times with `cache_prompt: true`:

| request | prompt_n (processed) | cache_n (reused) | time | rate |
|---|---|---|---|---|
| 1. first, cold | 55,460 | 0 | **184.76s** | 300.2 tok/s |
| 2. context grown by ~3.7k tokens | **3,720** | 53,408 | **15.76s** | 236.0 tok/s |
| 3. identical repeat | **4** | 57,124 | **0.32s** | — |

So the prompt cache does its job: growing the context costs only the *new* tokens, not the
whole prompt. A close-to-identical repeat costs essentially nothing (0.32s).

**This corrects the practical picture reported earlier in this work.** "A full-context prefill
costs ~30 minutes" is the *cold* number — the first request of a session that has to prefill
everything. In steady state an agentic loop pays only for the increment: here, ~3.7k new
tokens against a 53k prefix cost 15.8s, against 185s for the same prompt cold. That is a ~12x
reduction in per-turn prefill cost, and it is the number a user actually experiences.

The incremental rate (236 tok/s) is lower than the cold rate (300 tok/s) because the new
tokens are prefilled at the *end* of a 53k context, where attention over the existing KV is
more expensive. So incremental cost grows with context length even though it is only paying
for new tokens — the cold ~142 tok/s at 251k and this 236 tok/s at 53k are consistent with the
same context-dependent falloff, just at different points on it.

## `--cache-ram`: the default is already enough, so "more cache" is not the lever here

`llama-server` defaults `--cache-ram` to **8192 MiB**, and this build does not set it. That
matters for the "maximum useful cache" goal, and the answer is that the default is sufficient:
flash-next's KV at `q8_0` is 13,056 bytes/token, so a **full 262,144-token prefix is ~3.4 GiB**
— well inside 8 GiB. Raising it would add host RAM pressure to the APU pool for a prefix that
already fits.

Not tested: whether `--cache-ram` larger than the default helps *concurrent* sessions, where
idle slots are saved to the prompt cache (`--cache-idle-slots`, default enabled, requires
cache-ram). With `--parallel 1` — what this build runs — there is a single slot and the prefix
stays in the live KV cache, so the prompt cache is barely exercised. On a multi-slot build it
would matter more.

## Method

```
POST /v1/chat/completions  {"messages":[{"role":"user","content":<doc>}],
                            "max_tokens":1, "stream":false, "cache_prompt":true}
```
`timings.prompt_n` is the tokens actually processed and `timings.cache_n` the tokens served
from the cache, so the split is reported by the server rather than inferred. Request 2 appends
~2000 tokens of the same corpus *after* the original document, so the prefix is preserved and
only the suffix is new — which is how an agentic context actually grows.

Note this is the opposite of what the prefill ladder measures: that uses `cache_prompt: false`
deliberately, to force a full re-prefill so rates are comparable across context sizes. Both are
correct for their question; the ladder answers "how fast is prefill", this answers "what does a
turn cost".

## Caveats

- One run, one corpus (this repo's own source and docs, ~3.3 chars/token). The cold/incremental
  split is structural and will hold, but the exact seconds are not precise.
- Measured on build v1 (no `ROCBLAS_USE_HIPBLASLT`). v2's +4.6-9.5% prefill should reduce the
  cold number roughly proportionally; not re-measured.
- The ~3.7k-token increment was larger than the ~2,000 tokens appended, because the appended
  slice tokenizes denser than the corpus average and the boundary re-tokenizes. The appending
  size is approximate, the `prompt_n` figure is exact.
