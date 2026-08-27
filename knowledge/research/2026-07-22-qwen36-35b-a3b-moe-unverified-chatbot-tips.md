---
id: 2026-07-22-qwen36-35b-a3b-moe-unverified-chatbot-tips
date: 2026-07-22
source: "OPTIMIZATIONS.md (\"how about 35b-a3b, any optimizations there?\" section, lines 19-52)"
tags: [qwen, moe, strix-halo, vllm, docker, unverified, superseded]
status: superseded
---

# Qwen3.6-35B-A3B (MoE) on Strix Halo: early, low-confidence chatbot-sourced tips

**Finding (low confidence, unverified at time of writing)**: an AI-chatbot response
described Qwen3.6-35B-A3B as a sparse Mixture-of-Experts model (35B total / 3B active per
token) well-suited to Strix Halo's memory-bandwidth-bound profile, claiming ~25-45 tok/s
under standard configuration and 100+ tok/s with "optimized RDNA3 custom kernels." It
recommended Int4 AWQ quantization (BF16 needs ~70GB weights alone vs ~18-20GB for AWQ
Int4), an aggressive KV-cache-friendly context length (64K+, citing the model's Gated
DeltaNet layout reducing KV cache footprint by ~75% vs dense attention in 3 of every 4
blocks), and a Docker Compose template with `shm_size: 24gb`, `--max-model-len 65536`,
`--max-num-batched-tokens 32768`, and Triton-based sparse expert routing (8 of 256
experts active).

**Methodology / confidence**: not independently verified at time of writing — same
chatbot-response provenance as the companion Qwen3.6-27B tips
(`2026-07-22-qwen36-27b-unverified-chatbot-tips.md`). No source citation, no reproducible
benchmark attached.

**Status**: superseded by real, directly-measured benchmark data for this model on this
hardware (see `2026-07-22-qwen36-35b-a3b-real-benchmark-data.md` and the 2026-07-24
llama.cpp/vLLM benchmark research files). Real measured tg128 via llama.cpp direct came
in at 63.43 tok/s (Q4_K_M quant) — within the "standard configuration" range this note
predicted, but the specific mechanism claims (custom RDNA3 kernels, 100+ tok/s) were never
independently reproduced. The general architectural reasoning (MoE favors this
memory-bandwidth-bound hardware; AWQ/Int4 quantization is worth pursuing for footprint)
held up directionally in later verified research, even though the specific numbers here
should not be trusted as-is.
