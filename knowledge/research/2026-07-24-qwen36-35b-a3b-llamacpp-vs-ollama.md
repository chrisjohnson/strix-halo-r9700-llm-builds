---
id: 2026-07-24-qwen36-35b-a3b-llamacpp-vs-ollama
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Qwen3.6-35B-A3B GGUF benchmark: llama.cpp direct vs Ollama\", lines 260-290)"
tags: [qwen, moe, benchmark, llamacpp, ollama, vulkan, strix-halo]
status: active
---

# Qwen3.6-35B-A3B GGUF: llama.cpp direct vs Ollama benchmark (active-params-vs-speed pattern, third confirmation)

**Finding**: benchmarked `unsloth/Qwen3.6-35B-A3B-GGUF` Q4_K_M (22.1GB on disk, 34.66B
params). Same house methodology as the Gemma-4-26B-A4B and Qwen3.6-27B GGUF runs.

**llama.cpp direct**: pp512 = 1075.81±21.68 tok/s, tg128 = 63.43±0.30 tok/s — the fastest
tg128 recorded for the Qwen3.6 family via llama.cpp direct on this hardware at the time,
beating the sibling dense Qwen3.6-27B (12.75 tok/s) by close to 5x — same underlying
model-generation architecture, differing only in dense-vs-MoE shape. The earlier vLLM-side
comparison for these two models showed a similar but smaller gap (33.19 vs 17.91 tok/s
@c8, ~1.85x) — llama.cpp direct's cleaner single-stream measurement makes the
architectural effect look larger. Still behind GLM-4.7-Flash's 70.1 tok/s (smaller
~3B-active MoE, smaller total footprint) and just ahead of Gemma-4-26B-A4B's 53.96 tok/s.

**Ollama**: registration succeeded (Qwen3.6-35B-A3B is a recognized architecture, same
family tag as the already-proven dense 27B file). Real generation request succeeded:
`eval_count: 1511`, `eval_duration: 135177304222` ns → 11.18 tok/s — roughly a 5.7x gap
vs. llama.cpp direct, much closer to GLM-4.7-Flash's ~5.4x gap than to dense
Qwen3.6-27B's comparatively narrow ~17% gap.

**Pattern flagged (hypothesis, not yet a settled conclusion at time of writing)**:
Ollama's overhead cost relative to llama.cpp direct looks architecture-dependent, not a
flat tax — the two MoE models measured so far (GLM-4.7-Flash ~5.4x, Qwen3.6-35B-A3B
~5.7x) both show a large gap; the one dense model measured (Qwen3.6-27B, ~17%) shows a
much smaller one. Plausible explanation: Ollama's Go scheduling/wrapper layer may interact
poorly with MoE expert-routing overhead specifically — but this is only two MoE data
points and one dense data point, not a controlled ablation.

**Net conclusion**: llama.cpp direct remains the benchmark-of-record for this model —
pp512 1075.81 tok/s / tg128 63.43 tok/s. Ollama works (no architecture blocker) but at
roughly 1/6th the generation speed.

**Separate operational lesson from this same session**: restarting the download queue and
`vllm-primary`/`vllm-judge` simultaneously right after this benchmark overloaded host
memory (~92GiB used / 2-7GiB free against a 124GiB pool while a 66.97 GiB checkpoint was
mid-load), causing both vLLM engine-core processes to be SIGKILLed (OOM-killer signature).
Fix: pause downloads, restart vLLM alone, confirm healthy, then resume downloads —
sequence memory-heavy operations rather than running them in parallel, especially right
after a 66GB+ model load.
