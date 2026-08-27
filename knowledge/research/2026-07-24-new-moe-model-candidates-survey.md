---
id: 2026-07-24-new-moe-model-candidates-survey
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Fourth pass — Lead 3: new small-active-param MoE model candidates\", lines 336-348)"
tags: [model-candidate, moe, huggingface, survey]
status: active
---

# New small-active-param MoE model candidates: survey results

**Finding**: searched HuggingFace's API directly (not a cold-recall list) across Qwen,
Google/Gemma, Z.AI/GLM, DeepSeek, Mistral, MiniMax, and Moonshot/Kimi for anything in the
same ~30B-total/~3B-active shape (or comparably favorable active-fraction) as the models
already winning on this hardware (Gemma-4-26B-A4B, Qwen3.6-35B-A3B, GLM-4.7-Flash).

- **`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`** — confirmed real via HF API (31.58B total
  params BF16, `nemotron_h` architecture), released 2025-12-04. Smaller sibling of the
  already-owned `NVIDIA-Nemotron-3-Super-120B-A12B`, same hybrid mamba/attention family
  and publisher, in the exact size class that had performed best here. Not yet in kyuz0's
  benchmark dataset, no direct gfx1151 evidence yet. **Strongest new candidate found this
  pass** — a GGUF conversion already exists (`bartowski/nvidia_Nemotron-3-Nano-30B-A3B-GGUF`).
- **`moonshotai/Kimi-Linear-48B-A3B-Instruct`** — confirmed real (49.12B total params
  BF16, custom `kimi_linear` architecture), released 2025-10-30. Same ~3B-active ratio as
  the current winners but a meaningfully larger total footprint (49B vs. the 30-35B sweet
  spot) — ~25-28GB at 4-bit quant. A hybrid linear-attention design, conceptually similar
  to Qwen3.6's Gated DeltaNet. No gfx1151 evidence found. Moderate-confidence candidate.
- **`mistralai/Leanstral-1.5-119B-A6B`** — real repo, released 2026-07-01, but safetensors
  metadata not exposed via the API (likely gated/LoRA-shaped). 119B total/6B active is a
  noticeably larger and higher-active-param tier than current favorites (~4x total size,
  2x active params). Lower-confidence, flagged mainly for completeness.
- **`Qwen/Qwen-AgentWorld-35B-A3B`** — real, released 2026-06-22, same 35B-total/3B-active
  architecture as this project's own primary model, but explicitly not a general-purpose
  chat/coding model — a specialized "language world model" for simulating agentic
  environment state transitions. Not a real candidate for this project's use case.
- **Z.AI/GLM**: no new small-active-param sibling to GLM-4.7-Flash found; the GLM-5.x line
  all stays at flagship scale.
- **DeepSeek**: nothing new in the small-active-param class; recent additions are
  draft-model/speculative-decoding artifacts for other base models, not new MoE
  checkpoints of their own.
- **MiniMax**: MiniMax-M3 and the already-owned M2.7 remain large-tier releases, no small-
  active-param sibling in this family.

**Net assessment**: Nemotron-3-Nano-30B-A3B is a genuinely strong, verified, previously-
unsurveyed candidate directly in this hardware's proven-best size class, from the same
publisher as an already-owned/working model family. Kimi-Linear-48B-A3B is a real,
moderate-confidence, somewhat-larger candidate worth keeping on the list. No downloads
were started for any of these at time of writing — recorded per the standing two-step
download gate (research/record now, human approves the actual download separately).
