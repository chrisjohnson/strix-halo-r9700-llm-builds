---
id: 2026-07-24-lemonade-ollama-verified
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Lemonade Server & Ollama — verified against official sources\", lines 107-118)"
tags: [lemonade, ollama, npu, rocm, strix-halo, verified]
status: active
---

# Lemonade Server and Ollama: verified against official sources (corrects earlier Reddit-based speculation)

**Finding — Lemonade Server**: Hybrid Mode (NPU + iGPU together, the entire reason
Lemonade was of interest) is **Windows-only, full stop**. Confirmed verbatim from the
project's own FAQ (`github.com/lemonade-sdk/lemonade/blob/main/docs/guide/faq.md`):
"Ryzen AI SW's implementation of NPU and hybrid inference is currently supported only on
Windows." Linux and Docker are genuinely supported (official image
`ghcr.io/lemonade-sdk/lemonade-server:latest`, OpenAI-compatible API at `/v1`), but on
Linux Lemonade's own GPU story for this chip is "use the experimental `vllm:rocm`
backend" — i.e. the same vLLM already running on this box. **Conclusion: not worth
pursuing.** It would not touch the idle NPU on this machine's actual OS; it would just be
a second OpenAI-compatible server duplicating vLLM's existing GPU-only path.

**Finding — Ollama**: mechanically straightforward to run (official `ollama/ollama:rocm`
image, same device-mount pattern as the existing vLLM containers, gfx1151 officially
listed as supported hardware), but two open upstream regressions on Linux/gfx1151 were
identified at time of writing:
- `ollama/ollama#13589` (open at the time): gfx1151 silently falls back to CPU despite
  `rocminfo` correctly detecting the GPU.
- `ollama/ollama#15336` (open at the time): a regression where 0.17.7 worked on Strix
  Halo but 0.18.x+ broke GPU detection.

**Implication drawn at the time**: any Ollama benchmark data must be validated against
actual GPU utilization (not just "the container started and returned tokens"), and
pinning to ≤0.17.7 was recommended over `latest`/`rocm` unqualified.

**Methodology**: re-researched directly against official docs/repos (not a cold model
query) specifically because the prior Reddit-thread-based research
(`2026-07-23-npu-igpu-hybrid-inference-reddit-thread.md`) was flagged as low-confidence.

**Status note**: both `#13589` and `#15336` were later found to be closed/resolved, and
the "0.17.7 vs 0.18.x+" framing was found to be stale — see
`2026-07-24-ollama-version-tradeoff-reassessed.md` for the corrected, more nuanced
picture (a real 0.30+ regression exists instead, with a known workaround). The Lemonade
conclusion above still stands as of the last check.
