---
id: 2026-07-24-third-pass-gemini-factcheck
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Third pass: fact-checking a cold Gemini query\", lines 131-150)"
tags: [gemini, factcheck, unverified, benchmark, methodology]
status: active
---

# Fact-checking a cold Gemini query: real leads kept, fabricated numbers caught and rejected

**Context**: a different AI (Gemini, no confirmed tool access) was asked the same kind of
research question cold, across three rounds (model/engine recommendations, then
refinement for concurrent multi-agent/large-context workloads, then a further refinement
after one claim was caught as wrong). Every specific, checkable claim was verified against
a real source before being trusted.

**Held up (real, sourced, kept)**:
- A four-row model performance table (GPT-OSS-120B, Qwen3.5-122B-A10B,
  NVIDIA-Nemotron-3-Super-120B-A12B, MiniMax-M2.7) — all four verified as genuine entries
  in kyuz0's raw `results.json`. Nemotron-3-Super and MiniMax-M2.7 were new candidates not
  previously considered; both were approved and downloading as of this pass.
- `llama.cpp build 9193` — real, exact build hash from the same benchmark dataset.
- `rocWMMA` (`GGML_HIP_ROCWMMA_FATTN`) for ROCm flash-attention on long context — real,
  independently corroborated optimization flag, though not part of the cited dataset.
- `amd-ttm` — a real AMD-published CLI tool, a runtime-equivalent to the existing
  boot-param approach (`amdgpu.gttsize`/`ttm.pages_limit`), not a superior alternative.
- PagedAttention/continuous-batching reasoning for multi-tenant serving — accurate,
  standard vLLM architecture.

**Fabricated or unverifiable — rejected**:
- Two separate wildly-inflated throughput claims for Qwen3.6-35B-A3B ("~300 t/s," then
  "~181 tokens/sec (vLLM ROCm TP1)," framed as "verified"). This project's own real
  directly-measured number for the same model is 33.19 tok/s at concurrency 8 — over 5x
  lower than the second claim, with no real checkable source behind either figure.
- DeepSeek V4 Flash recommendation — self-corrected by Gemini itself after being caught
  (already disqualified elsewhere in this project's research for being too large even
  quantized).
- FP8 KV cache framed as a real performance win — this hardware has no FP8 matrix-core
  compute at all; no evidence it delivers a real speedup vs. emulating at BF16 speed.
  "Configure LiteLLM to use FP8 KV caching" was also a category error (LiteLLM is a
  routing gateway with no KV cache to configure).
- A specific claim of a "July 2026 build" fixing "Q8_0/Q4_0 KV-cache decode collapse,
  +30-50%" — unverifiable; adjacent real work exists but nothing ties to this specific
  claim or figure.
- A Llama 3.1 70B AWQ-4bit figure — admitted by Gemini itself to be unbenchmarked
  (extrapolated from the already-debunked 181 tok/s figure). No such entry exists in
  kyuz0's actual benchmark data.
- "MLX Engine ROCm backend... beating vLLM by up to 85%... simultaneous GPU+NPU
  execution" — the most instructive fabrication: `lemon-mlx-engine` is a real project and
  the cited GitHub issue is real, but the benchmark numbers inside that issue trace back
  to a since-deleted GitHub account and a linked benchmark repo that 404s. Gemini repeated
  numbers from an already-unverifiable source as established fact.

**Takeaway**: a cold LLM query without real tool/browsing access can surface genuinely
useful candidate leads, but every specific number, benchmark claim, or "verified" framing
needs independent verification against a real, checkable source before being trusted. The
failure mode is not random noise — it's confident, specific-sounding fabrication (exact
tok/s figures, exact build numbers, named GitHub issues) that reads identically to real
findings until checked.
