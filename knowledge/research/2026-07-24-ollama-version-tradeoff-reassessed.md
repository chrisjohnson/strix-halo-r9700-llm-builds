---
id: 2026-07-24-ollama-version-tradeoff-reassessed
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Fourth pass — Lead 2: Ollama version tradeoff\", lines 321-334)"
tags: [ollama, rocm, vulkan, strix-halo, verified]
status: active
---

# Ollama version tradeoff reassessed: "0.17.7 vs 0.18.x+" framing is stale

**Finding**: the existing pin (`ollama/ollama:0.17.7`) and the belief that "0.18.x+
reintroduces a GPU-detection regression" were checked directly against current GitHub
state. Ollama had moved far past that range: latest stable release at time of writing was
v0.32.3 (2026-07-23) — 0.17.7/0.18.x was roughly 15 minor versions and several months
stale.

**Both issues previously cited in this project's research were re-checked comment-by-
comment, not just for open/closed status**:
- `ollama/ollama#13589` (gfx1151 falls back to CPU) — closed, `completed`. Real root
  cause: a rocBLAS GPU-kernel VM-fault that `HSA_OVERRIDE_GFX_VERSION` does not fix. Fix
  landed in Ollama 0.17.8 (bundles ROCm 7); a separate user later confirmed real ROCm GPU
  detection working as of 2026-04-17 on 0.18.3, conditioned on a kernel ≥6.17.0-19.19
  (Ubuntu HWE) and matching amdgpu userspace driver. **This directly contradicts the
  "0.18.x+ broke it" belief** — 0.18.x fixed it, conditioned on the host stack meeting
  newer requirements many reporters' systems didn't have at the time.
- `ollama/ollama#15336` ("0.17.7 last version working, 0.18.x fallback to CPU") — closed,
  `completed`. The reporter's own resolution: their real root cause was an old kernel
  (6.14.0-37-generic), not the Ollama version — upgrading to 6.17.0-20-generic fixed GPU
  detection on Ollama 0.20.2, and they explicitly confirmed "working perfectly with
  0.20.2 and gemma4" — both the GPU-detection issue and this project's own `gemma4`
  architecture gap resolve together on a modern release given a modern-enough kernel.
- This machine's actual kernel (6.18.39, confirmed via `uname -r`) clears every version
  bar mentioned in both threads.
- **`gemma4` architecture support** confirmed present since Ollama v0.21.0 (2026-04-16),
  with QAT weights added in v0.30.6, MTP for Gemma 4 in v0.23.1 (Mac-only), tool-
  calling/reasoning improvements in v0.32.1. The `unknown model architecture: 'gemma4'`
  failure this project hit on 0.17.7 would not reproduce on any Ollama release from the
  last ~3+ months at time of writing.

**A different, real, currently-open regression was found instead, more relevant than the
stale framing**: `ollama/ollama#16462`, "AMD Strix Halo VRAM Detection Regression in
Ollama 0.30+ (Container Deployment)," opened 2026-06-03, still open and actively commented
on as recently as 2026-07-22. Root cause (confirmed via an Ollama maintainer's own
comments): starting at Ollama 0.30.0, the ROCm backend under-reports available memory on
Strix Halo (reads `/proc/meminfo`'s `MemAvailable` rather than the real GTT/VRAM carveout),
capping usable memory at roughly free system RAM instead of the real ~100GB+ pool. Linked
to a still-open upstream llama.cpp issue rather than an Ollama-side fix. **Confirmed
workaround (multiple independent reporters)**: run the Vulkan image (`ollama/ollama:latest`,
non-`-rocm` tag) plus `OLLAMA_IGPU_ENABLE=1` — one reporter's before/after: broken ROCm
path capped at "27.9 GiB available" (GPT-OSS-120B spilled to CPU, 2.5 tok/s); Vulkan +
the flag correctly detected "111.1 GiB available" and ran the same model at 37.5 tok/s,
100% GPU.

**Revised bottom line**: the original "pin to 0.17.7" framing was never really an
Ollama-version story so much as a host-kernel-version story — both cited bugs trace to
reporters' kernels being too old, not the Ollama release. This box's kernel already clears
every bar mentioned. A real, currently-open regression exists in the 0.30+ line, but has a
clean, well-corroborated workaround (Vulkan/non-`-rocm` image + `OLLAMA_IGPU_ENABLE=1`) —
also sidesteps the separate HIP-integrated-GPU corruption bug found in the concurrent-
serving research. **Recommendation (not acted on at time of writing)**: if/when Ollama is
revisited, a modern release via the Vulkan image tag + `OLLAMA_IGPU_ENABLE=1` (not the
`-rocm` tag) is likely both the correctness-safe and `gemma4`-capable choice.
