---
id: 2026-07-22-qwen36-35b-a3b-real-benchmark-data
date: 2026-07-22
source: "OPTIMIZATIONS.md (\"Qwen3.6-35B-A3B real benchmark data — kyuz0 toolboxes site\", lines 91-105)"
tags: [qwen, moe, benchmark, llamacpp, rocm, vulkan, strix-halo]
status: active
---

# Qwen3.6-35B-A3B: real third-party benchmark data (kyuz0 toolboxes, gfx1151)

**Finding**: real, machine-generated benchmark data (not an LLM guess) for
`Qwen3.6-35B-A3B-BF16` on a Framework Desktop / Ryzen AI MAX 395+ / 128GB unified RAM
(same gfx1151 chip family as this project's box), across 5 backend environments
(`rocm-7_2_3`, `rocm6_4_4`, `rocm7-nightlies`, `vulkan_amdvlk`, `vulkan_radv`, all with
flash attention on, `ngl=99`).

- **Text generation (tg128)**: best result 26.01 tok/s (ROCm 7.2.3); ROCm 6.4.4 and
  ROCm-7-nightlies close behind (~25-26 tok/s); Vulkan RADV 10.68 tok/s, AMDVLK 11.6 tok/s
  — markedly slower for TG.
- **Prompt processing (pp512)**: ROCm 6.4.4 hit 573.71 tok/s, ROCm 7.2.3 525.94, ROCm
  7-nightlies 528.97; Vulkan RADV 328.4, AMDVLK 122.89. The often-cited "300+ tok/s" figure
  for this model is a prompt-processing (prefill) number, not a generation/decode number —
  a distinction that has caused confusion elsewhere (see the "Third pass" fact-check
  research file).
- **Quantized variants generate much faster than BF16**: Q4_K_XL tg128 best 60.43 tok/s
  (Vulkan RADV) / ~51 tok/s (ROCm), pp512 best 1120 tok/s (ROCm 7.2.3). Q8_K_XL tg128 best
  46.53 tok/s (Vulkan AMDVLK) / ~46 tok/s (ROCm), pp512 best ~1095 tok/s (ROCm).
- Longer contexts degrade both PP and TG somewhat (e.g. BF16 ROCm 7.2.3: pp2048@32k =
  417.86 tok/s vs pp2048@65k = 322.65 tok/s; tg32@32k = 23.91 tok/s vs tg32@65k = 22.2
  tok/s).

**Takeaway**: BF16 is the slowest option for actual token generation on this hardware
class (~26 tok/s ceiling) despite the fastest-looking prompt-processing numbers.
Quantized (Q4_K_XL/Q8_K_XL) variants roughly double-to-triple TG speed vs BF16. Backend
choice matters and is not uniform: ROCm wins prompt processing on BF16, but Vulkan RADV
wins TG on the quantized variants.

**Methodology**: source data pulled directly from
`https://kyuz0.github.io/amd-strix-halo-toolboxes/results.json` (the page renders this
JSON client-side; a plain page fetch alone only sees an empty shell, so the raw JSON was
fetched directly). Data generated 2026-05-18 on Fedora Linux 43, kernel 6.19.12.
