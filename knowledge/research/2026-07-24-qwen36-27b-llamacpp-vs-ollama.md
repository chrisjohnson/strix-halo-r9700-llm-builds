---
id: 2026-07-24-qwen36-27b-llamacpp-vs-ollama
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Qwen3.6-27B GGUF benchmark: llama.cpp direct vs Ollama\", lines 185-207)"
tags: [qwen, dense, benchmark, llamacpp, ollama, vulkan, strix-halo]
status: active
---

# Qwen3.6-27B GGUF: llama.cpp direct vs Ollama benchmark

**Finding**: benchmarked `unsloth/Qwen3.6-27B-GGUF` Q4_K_M (16.8GB on disk, 26.90B
params). Download queue (7 active units) and `vllm-primary`/`vllm-judge` were stopped
first to remove contention, then resumed/restarted after.

**llama.cpp direct** (`kyuz0/amd-strix-halo-toolboxes:vulkan-radv`): pp512 = 342.55±14.41
tok/s, tg128 = 12.75±0.03 tok/s — by far the slowest llama.cpp-direct generation number
recorded in this project up to that point, well behind both GLM-4.7-Flash (70.1 tok/s) and
Gemma-4-26B-A4B (53.96 tok/s), both MoE models with a fraction of Qwen3.6-27B's ~27B
*active* params per token. This is the second independent engine (after vLLM) confirming
a dense-architecture cost on this hardware.

**Ollama**: registration succeeded; unlike Gemma-4-26B-A4B, Qwen3.6 is a recognized
architecture on this Ollama build. A real `/api/generate` request succeeded (including a
`<think>` reasoning trace): `eval_count: 613`, `eval_duration: 57871769652` ns → 10.59
tok/s — about 17% below the llama.cpp-direct number, a much narrower gap than
GLM-4.7-Flash's ~5.4x Ollama-overhead gap. Caveat: this was a single real `/api/generate`
sample (with reasoning-mode token-count inflation), not an averaged `llama-bench`-style
run — directionally comparable, not a precise controlled ablation.

**Net conclusion**: Qwen3.6-27B works on both backends with no architecture blocker,
unlike Gemma-4. Both numbers are the slowest GGUF-based generation speeds recorded in this
project at the time, reinforcing that this model's dense (not MoE) architecture is the
dominant cost, not the serving engine.
