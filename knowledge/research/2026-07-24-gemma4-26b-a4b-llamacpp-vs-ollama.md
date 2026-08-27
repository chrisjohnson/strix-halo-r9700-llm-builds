---
id: 2026-07-24-gemma4-26b-a4b-llamacpp-vs-ollama
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Gemma-4-26B-A4B GGUF benchmark: llama.cpp direct vs Ollama\", lines 152-183)"
tags: [gemma, moe, benchmark, llamacpp, ollama, vulkan, strix-halo]
status: active
---

# Gemma-4-26B-A4B GGUF: llama.cpp direct vs Ollama benchmark

**Finding**: benchmarked the `unsloth/gemma-4-26B-A4B-it-GGUF` Q4_K_M file (15.77 GiB,
25.23B total params) on both backends, same file, clean backend-only comparison.

**llama.cpp direct** (`kyuz0/amd-strix-halo-toolboxes:vulkan-radv`): two runs, one
contaminated by a concurrent background model download (pp512 1192.75±11.10 tok/s, tg128
54.50±0.29 tok/s), one clean (pp512 1251.33±17.08 tok/s, tg128 53.96±0.15 tok/s). PP
dropped ~4.9% under concurrent download load; TG was statistically unaffected (well within
run-to-run noise) — consistent with TG being purely GPU-memory-bandwidth bound per token,
a regime background CPU-side downloads don't meaningfully compete in. **Benchmark of
record: pp512 1251.33 tok/s / tg128 53.96 tok/s (clean run).**

**Ollama**: registration succeeded, but a real chat/generate request failed outright with
`unknown model architecture: 'gemma4'` — Ollama 0.17.7's bundled ggml/llama.cpp build does
not recognize the `gemma4` GGUF architecture tag. Confirmed via `docker logs` (GGUF
metadata parses fine; failure is specifically at architecture-dispatch) and `/api/version`
(confirms the expected 0.17.7 pin, not a stale image). Not a config problem or something a
retry fixes — this Ollama version genuinely cannot serve this model. A newer Ollama build
likely supports `gemma4` but was, at the time, believed to reintroduce a GPU-detection
regression on 0.18.x+ (see `2026-07-24-ollama-version-tradeoff-reassessed.md` for the later
correction to that belief).

**Comparison note**: markedly *slower* on both axes than GLM-4.7-Flash's benchmark-of-
record (81.3 PP / 70.1 TG, same methodology) despite Gemma-4-26B-A4B having posted the
best vLLM concurrency/coding-benchmark results of anything tested at the time — a reminder
that vLLM-serving fitness and raw llama.cpp/GGUF decode speed don't necessarily rank
models the same way.

**Net conclusion at time of writing**: llama.cpp direct was the only backend able to serve
this exact file at all — a hard architecture-support blocker for Ollama on this specific
model, not a speed disadvantage (contrast with GLM-4.7-Flash, where Ollama worked but was
~5.4x slower than llama.cpp direct).
