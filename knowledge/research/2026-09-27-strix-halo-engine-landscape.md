---
id: 2026-09-27-strix-halo-engine-landscape
date: 2026-09-27
source: survey of Strix Halo inference engines, 2026-09-27 — starting from /u/ilintar's r/LocalLLaMA post "Qwen3.8 Flash Next now at 1.2k t/s prefill on Strix Halo" (https://www.reddit.com/r/LocalLLaMA/comments/1weobt6/) and following it to pwilkin/strix-halo, kyuz0/amd-strix-halo-toolboxes and kyuz0/gufo
tags: [strix-halo, prefill, qwen3.8-flash-next, llama.cpp, rocm, retained-pm4, gufo, engine-survey]
status: active
---

# The Strix Halo engine landscape, and where the prefill speed actually lives

Written after this repo's own flash-next work reached ~500 tok/s prefill and a community
result claimed ~1,200. Both numbers are real; they are different engines on the same silicon.

**First, a correction to how this arrived.** The URL slug reads `12k_ts_prefill`, but the post
title is "Qwen3.8 Flash Next now at **1.2k** t/s prefill" — 1,200 tok/s, not 12,000. Worth
stating because a 10x error at the top would have poisoned everything downstream.

## The result that started it

`/u/ilintar` is a llama.cpp maintainer. His writeup —
<https://pwilkin.github.io/strix-halo/journey.html> — is the best-measured work in this space:
16+ commits, each with error bars and a stated multiplier, **negative results kept** (his
sparse-attention path measures break-even, 0.98-1.01x, and he says so), the out-of-tree
reference stack re-run the same day as a control, and a 150,300-token needle-in-a-haystack
correctness test before trusting the sparse kernels.

Route: **191 -> ~1,200 tok/s pp16384 (6.07x)**, ~947 tok/s over a 150k-token prompt.

The steps that matter, and which of them we already have:

| Their step | Worth | Do we have it? |
|---|---|---|
| `964c6f2f0` tiled gated delta-net | **2.37x** | **No.** This is the big one. |
| bf16 WMMA dequant GEMM | 1.42x isolated | No |
| maskless KQ path | 1.48x isolated | No |
| `ddaf5214b` lazy direct reader (`--lazy-mode on-direct`) | 1.69x isolated, 2.75x on their finished stack | **Partly** — we ported upstream PR #29030 and measured +22-29% |
| fused HC gate GEMM + mix | 1.19x | No |
| depthwise conv1d + vectorized get_rows | 1.08x | No |
| sparse attention | break-even | n/a, they gate it off |

**The lazy-direct entry is the useful cross-check.** We got +22-29% from the same mechanism;
they get 2.75x. The difference is visible in the command line: they run `-ub 24576`, we run
`-ub 2048`. In their words, *"Demand paging serialises 16384 scattered faults per ubatch in
the fault handler"* — a bigger ubatch means far more serialisation for the direct reader to
remove, so the same feature is worth far more at their batch width. Our own `-ub 8192`
attempt blew the memory budget, but that was with mmap; their config is `--load-mode none`,
which changes the layout entirely.

**And it corrects our GDN result.** They note a *chunked* delta-net rewrite "measured ... at
roughly 3% end-to-end and dropped it", comparing chunked against **tiled**. Our
`GGML_HIP_GDN_CHUNK=1` is the chunked path, and we measured +7.4-10.7%. Same story: the flag
is real but small; the tiled kernel is the prize, and it is kernel work, not a flag.

## The engines available

| Engine | Prefill | Where | Cost to try |
|---|---|---|---|
| **`kyuz0/gufo`** | **1,628.52 tok/s pp** (Qwen3.8-Flash-Next Q4_K_XL) | `ghcr.io/gufo-org/toolboxes/gufo-runtime:latest`, `kyuz0/amd-strix-halo-toolboxes:rocm-10.0-gufo` | **Pull an image** |
| `pwilkin/llama.cpp@strix-halo` + retained-PM4 | ~1,200 pp16384 | source | Build 40-60 min (Dockerfile vendored here) |
| `halo-box/strix-llama.cpp@master` + retained-PM4 | 1,207 pp2048 @d0, 1,055 @32k, 43.9 decode | source | Same Dockerfile, different args |
| our EngramHalo fork + PR #29030 | ~500 | this repo | built and measured |
| `rocm-10.0-qwen-3.8-flash-next` | not stated | `drluoto/llama.cpp@strix-halo-flash-next` | published toolbox |
| `vulkan-radv-performance` | not stated | `Nathanw1014/llama.cpp@strix-halo-vulkan` | published toolbox |

**`gufo` is the headline and was not the thing that got linked.** It is kyuz0's own engine —
not a llama.cpp fork, a from-scratch C++/HIP inference engine for gfx1151, MIT licensed — and
its README claims **1,628.52 tok/s pp, 59.41 tok/s single-user decode, and 157.22 tok/s
aggregated across 8 concurrent requests** on Qwen3.8-Flash-Next Q4_K_XL with MTP. It also
covers Qwen3.8-27B, DeepSeek-V4-Flash, and audio/image/video models. It runs on a **ROCm 7.2.3**
toolchain, not ROCm 10.0, and ships an OpenAI-compatible `gufo serve llm`, so it could sit
behind litellm directly if it holds up.

Its design notes are worth reading for their own sake — "preserve quality when optimizing",
"don't reuse kernels across different models to limit blast radius" — and its reference list
names the other Strix Halo forks: `LaurentZuijdwijk/llama.cpp`,
`Nathanw1014/strix-halo-llamacpp`, `gaetan-puleo/llama-cpp-strix-halo`.

## What this repo has done about it

`docker/pwilkin-strix-halo/Dockerfile.rocm-10.0-strix-llama` — kyuz0's containerized port of
pwilkin's installer, adapted here for docker, with the revisions **pinned** (kyuz0 deliberately
never pins: "a --no-cache build always takes branch HEAD"). It self-gates: it runs
`test-backend-sched-ring`, greps `DEBUG_HIP_GRAPH_PM4` out of the built `libamdhip64.so`, and
`ldd`-checks the custom libraries. See that directory's README for the operational warnings
that would otherwise cost real time — above all **never set
`GGML_CUDA_ENABLE_UNIFIED_MEMORY`**, which corrupts MTP output under HIP graphs on this device.

Also worth knowing: kyuz0 maintains a newer benchmark site, <https://local-llm-benchmarks.dev/>,
explicitly with "improved methodology and interactive benchmark curves" — relevant given this
repo's own finding that a repeated-filler prompt cannot exercise the PLE/ngram table and
inflates prefill rates (`2026-09-27-prefill-bench-padding-trap.md`).

## Caveats before trusting any of these numbers

- Theirs are `llama-bench`/engine-native on **Q4_K_XL or IQ4_NL**; ours are UD-IQ4_XS through
  `llm-inference-bench`. Different quant, different harness, different definition of "prefill".
  An engine comparison must hold the weights fixed.
- Their depth testing goes to 40k and 150k. Our production target is **262,144**.
- `--lazy-mode on-direct` is a **rename** of `--tensor-read-lazy` with new semantics, not an
  extra mode; there is no separate `on` any more.
- The `gufo` figures are the project's own README, not independently reproduced here.
