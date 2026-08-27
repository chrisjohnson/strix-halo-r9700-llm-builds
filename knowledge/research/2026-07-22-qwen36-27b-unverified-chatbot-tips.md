---
id: 2026-07-22-qwen36-27b-unverified-chatbot-tips
date: 2026-07-22
source: "OPTIMIZATIONS.md (opening \"qwen3.6-27b tok/sec on strix halo 128gb\" section, lines 1-16)"
tags: [qwen, strix-halo, vllm, unverified, superseded]
status: superseded
---

# Qwen3.6-27B on Strix Halo: early, low-confidence chatbot-sourced tips

**Finding (low confidence, later flagged as likely partly fabricated)**: an AI-chatbot
response (source/model unclear from the original text) claimed Qwen3.6-27B token
generation on a 128GB Strix Halo system ranges from ~4 tok/s (BF16 unquantized) up to
"101-134+ tok/s" using "custom RDNA3 kernels" and aggressive sub-4-bit quantization, with
intermediate figures for GGUF quants (Q6_K ~8.7 tok/s, Q4_K_M ~12-15 tok/s) and MTP-
enabled setups (25-50 tok/s). It also listed a performance checklist: set
`HSA_OVERRIDE_GFX_VERSION=11.5.1`, `HSA_ENABLE_SDMA=0`, `GPU_MAX_HEAP_SIZE=100`, and keep
`--spec-draft-n-max` between 2-3 for MTP.

A companion response gave vLLM-specific guidance: BF16 3.9-4.2 tok/s, AWQ Int4 14-18
tok/s, a Docker Compose template requiring Linux kernel ≥6.18.4 and ROCm ≥7.2, and flag
explanations for `--vllm-attention-backend triton`, `--quantization awq`,
`--gpu-memory-utilization 0.90`.

**Methodology / confidence**: none of this was independently verified at the time it was
recorded — it reads as generic AI-chatbot output (specific-sounding numbers and tool
names like "Chadrockv2 Profiles" that could not be corroborated). A later research pass
(see `2026-07-24-qwen36-27b-llamacpp-vs-ollama.md` and
`2026-07-24-third-pass-gemini-factcheck.md`) explicitly flagged this content as
unverified and cautioned against treating it as fact.

**Status**: superseded by real, directly-measured benchmark data for the same model on
the same hardware class (see the 2026-07-24 llama.cpp-direct-vs-Ollama benchmark research
files in this directory). The real measured tg128 for Qwen3.6-27B via llama.cpp direct
was 12.75 tok/s — in the same range as this early note's low-end GGUF estimate, but the
upper-end "101-134+ tok/s" and MTP "25-50 tok/s" claims were never reproduced or
corroborated by any later, verified research in this project.
