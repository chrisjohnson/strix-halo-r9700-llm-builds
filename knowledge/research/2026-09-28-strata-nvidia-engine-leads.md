---
id: 2026-09-28-strata-nvidia-engine-leads
date: 2026-09-28
source: reading github.com/Niko1221/Strata (MIT, C++, 1,081 stars, created 2026-09-24) and its docs/DETAILS.md, 2026-09-28 — an inference engine that runs the SAME model, Qwen3.8-Flash-Next, on a 12-24 GB NVIDIA card plus 64 GB of system RAM
tags: [flash-next, strata, quantization, speculative-decoding, memory-bandwidth, unified-memory, leads]
status: active
---

# What an NVIDIA engine for the same model has that we can use

Strata runs Qwen3.8-Flash-Next on one 12-24 GB NVIDIA card and 64 GB of RAM, at 52-90 tok/s output
and 1,070-1,350 tok/s prompt processing. It is NVIDIA-only (**the docs mention AMD exactly once,
as a CPU vendor**), so the engine is not portable. But it is built from parts of llama.cpp/ggml,
runs the same model, and its write-up contains two things worth having: measured numbers to
calibrate against, and a model-side lead that is bigger than anything left in our flag surface.

## The calibration, which is the most useful part

Their prompt processing against ours, both on the same model:

| context | Strata, RTX 5070 12 GB | ours, Strix Halo APU |
|---|---|---|
| 4K | 737-1,152 | ~790 (real text, ~75k prompt) |
| 32K | 1,070-1,308 | 1,256 |
| 64K | 1,065-1,350 | 1,306 |
| 128K | 931-1,266 | 1,264 |
| 262K | 886-1,034 | — |

**Our prefill already matches a purpose-built engine on a discrete NVIDIA card.** That is a strong
signal that prefill is finished, and it is worth more than any remaining flag: there is no large
prefill win left to chase on this hardware.

Output is where we differ - they do 52-90 tok/s, we do 23-34. **And that gap is the memory
bandwidth ratio.** The 5070 has roughly 672 GB/s against Strix Halo's ~256, i.e. ~2.6x, and 90/34
is ~2.6. Decode on the APU is bandwidth-bound and already at the wall. So the remaining headroom is
**not compute** - it is **bytes per token**. Every lead below is that, and any lead that promises
more compute is suspect.

## The lead that does NOT transfer, and why it looked like it would

Strata's core mechanism is splitting each token's experts between the **GPU's VRAM** and the
**CPU's system RAM**, computing the uncached experts on the CPU *at the same time* as the GPU works
on the cached ones. On their box that is genuinely two memory pools - ~672 GB/s of GDDR6X and
~80-100 GB/s of DDR5 - so working both at once adds bandwidth.

**I initially took this as a lever for us and it is not.** Strix Halo's CPU and iGPU share ONE
LPDDR5X pool and one memory controller, ~256 GB/s total. There is no second bandwidth source to
overlap with; `--n-cpu-moe` would move bytes onto a path that competes for the same ceiling. The
mechanism works *because* their GPU is discrete, which is precisely what ours is not.

Worth testing once anyway, since it is free with our existing weights and our engine supports
`--n-cpu-moe N`, `--cpu-moe` and `-ot` - but the reasoning says it will be neutral-to-worse, and
the earlier casual dismissal ("not applicable, everything is already on the GPU") reached the
right answer for the wrong reason.

## The leads that do transfer

**1. Swift 1.5 - a fine-tune trained to reach the answer with much less thinking.** Their docs
say its authors claim **63% fewer thinking tokens**. This is the largest applicable lead, because
it targets the term that actually dominates our agentic metric: our measured turn latency is
thinking-bound, not prefill-bound, and the same thinking is what produces the empty-content
failure at small caps. `ukisai/Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF` (~68 GB at IQ2_XS).
Quality is the open question; it is a fine-tune, so it must be measured rather than assumed.

**2. The GSQ-RCO quantizations - roughly 40 GB smaller than what we run.**
`ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF` (503k downloads, 360 likes): Q2_0 66 GB / ~40 GB
resident, IQ2_XS 68 GB / ~42 GB, IQ3_XXS 76 GB / ~49 GB, against **our UD-IQ4_XS at 88 GB**. Two
effects, both pointed the right way on a bandwidth-bound box: fewer bytes per token (faster
decode), and ~40 GB of RAM freed - which is exactly what the levers that FAILED were short of
(`--parallel 2` died on compute buffers; a larger prompt cache and a larger ubatch both wanted
memory we did not have).

The cost is quality, and it is a real one: IQ4_XS is a 4-bit quant and these are 2-3 bit. Their
README claims IQ3_S "matches the full model on the published tests", but that is against the
*full* model, not against IQ4_XS. Measure it, do not assume it.

**3. The Coder - half the experts, for code.** `ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF`.
A pruned model for coding, which is what our roles are actually used for. Smaller and faster by
construction; the question is whether it is still good enough at agentic work.

**4. `--calibrate` as a methodology.** Their setup measures a few engine settings on the user's own
machine and keeps the fastest, ~5-10 minutes, worth 7% on their box. We have done this by hand,
lever by lever. A scripted search over the flags we have not crossed (spec draft width, cache
reuse, defrag threshold, `swa-full`) is the same idea with better coverage than a human sweep.

**5. Their flag surface is a checklist of what a mature engine for this model tunes:** `--prefill
auto`, 8-bit KV above 4K, KV streaming from 64K, MTP on, expert routing profiles. Of those,
**8-bit KV is impossible for us** - our engine asserts f16 at `qwen4exp.cpp:1365`, already
established - and KV streaming is moot because our KV is in host RAM already. But it confirms the
direction: a purpose-built engine also lowers KV precision at long context, and we cannot.

## What was checked and found absent

- **No AMD/ROCm/Vulkan path at all.** NVIDIA driver required; the one AMD mention is as a CPU.
- **No hardware near ours** in its estimates (RTX 5060 Ti, 3090), so nothing to compare directly
  beyond the 5070.
- **The "experimental speed projection" is not a speedup.** It is a refusal-direction control
  vector: it removes a safety behaviour, costs 0.2-0.4% per token, and shifts ordinary answers
  (perplexity +15% on code). Flagged because it is presented under a speed heading; it is a
  behaviour change with a small cost, and enabling it is a judgement call about safety, not tuning.
