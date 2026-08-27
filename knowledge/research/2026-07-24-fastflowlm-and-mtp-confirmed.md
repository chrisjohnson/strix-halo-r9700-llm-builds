---
id: 2026-07-24-fastflowlm-and-mtp-confirmed
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Second deep-dive pass: FastFlowLM and confirmed-working MTP\", lines 119-129)"
tags: [fastflowlm, npu, mtp, llamacpp, speculative-decoding, qwen, strix-halo, verified]
status: active
---

# FastFlowLM (real NPU answer) and confirmed-working MTP speculative decoding

**Finding 1 — FastFlowLM**: a real, actively-maintained, current Linux-native answer to
the idle-NPU problem on Strix Halo, independent of Lemonade
(`github.com/FastFlowLM/FastFlowLM`). Explicitly lists Strix Halo as supported, added
native Linux support March 2026, and AMD itself announced integration with it in July
2026. Runs LLM inference entirely on the NPU (no GPU/CPU load), with an Ollama-like
CLI/API. Real requirements: Linux kernel 7.0+ (or the `amdxdna-dkms` backport), NPU
firmware ≥1.1.0.0, and AMD IOMMU must be enabled. Caveat: enabling IOMMU for NPU use may
cost a small amount of iGPU throughput (one community report: +3.29% latency on a
concurrent 64K iGPU workload) — a real tradeoff, not free. A known Ubuntu 25.10
firmware/driver mismatch bug is open upstream (`amd/xdna-driver#1219`) — worth checking
against this box's actual NixOS kernel/firmware pairing before attempting setup.

**Finding 2 — MTP speculative decoding is confirmed working, via llama.cpp, not vLLM**:
llama.cpp merged native MTP support (`ggml-org/llama.cpp` PR #22673, merged 2026-05-16)
for models shipping MTP heads, including Qwen3.6-27B and Qwen3.6-35B-A3B (both already
in this project's model lineup). Specifically benchmarked on Strix Halo/gfx1151 in two
independent places (kyuz0's `mtp.html` page, calebcoffie.com): reported speedups of
1.8x-2.5x (e.g. Qwen3.6-27B Q4_K_M going from 11.7 to 21.2 tok/s), draft acceptance rate
~72% at depth 3. Real caveats: `n_parallel=1` only (no concurrent request serving while
using MTP), and ROCm+tensor-parallel combinations reportedly crash — Vulkan is the safer
backend. No vLLM MTP evidence was found on this hardware; vLLM's `qwen3_next_mtp` path
remains unconfirmed on ROCm.

**Other serving backends checked, mostly dead ends**: SGLang has no official ROCm support
for gfx1151 (community-patched image exists but unproven/non-upstream); MLC-LLM has no
gfx1151 evidence; ExLlamaV2/TabbyAPI have no AMD/ROCm support at all. llama.cpp run
directly (not via Ollama) is the clearly worthwhile alternative — Vulkan/RADV frequently
beats ROCm for token generation on this chip, and exposes MTP, which Ollama's bundled
llama.cpp build does not.

**Also found — new model candidate**: `CohereLabs/North-Mini-Code-1.0-w4a16`, 30B
total/3B active MoE, released June 2026, purpose-built for agentic coding, ~18-20GB on
disk, 256K context, native vLLM `cohere_command4` tool-call parser. Zero direct
Strix-Halo evidence yet at time of writing (too new). Disqualified in the same pass:
GLM-5.2 (743B total, too large even quantized), DeepSeek V4 Pro/Flash (1.6T total, same
reason).

**Methodology**: this was an explicit follow-up pass requested to check whether the
earlier two research passes were genuinely thorough, not a shallow first hit. Each claim
above was independently verified via direct source checks (GitHub, project docs), not a
cold model query.
