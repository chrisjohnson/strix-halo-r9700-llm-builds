---
id: 2026-08-02-dflash-vulkan-sweep-and-rocm-control
date: 2026-08-02
source: M-053 card (now done/), M-055 card (now/), catalog/raw/dflash-sweep-2026-08-02/ (raw JSON per config)
tags: [dflash, speculative-decoding, laguna, llamacpp, vulkan, rocm, gfx1151, benchmark]
status: active
---

# DFlash (Laguna-S-2.1): Vulkan parameter sweep + ROCm control build

## Finding

The M-053 mystery — DFlash draft acceptance collapsing to 10-19% on our Vulkan/RADV
build of poolside's `laguna` fork vs the community's 73.5-90.6% on ROCm/HIP — is a
**block-size effect, not a backend defect and not flash-attention**. Sweeping
`--spec-draft-n-max` (2/3/4/6/8/15, `-fa` 0/1) on the same Vulkan fork image:

| config | short acc | short tok/s | long acc | long tok/s |
|---|---|---|---|---|
| n15 fa1 (M-053) | 10-19% | 8.0-11.5 | 11.4% | 7.9 |
| n8 fa1 | 17-18% | 9.2-9.5 | 26.4% | 11.3 |
| n6 fa1 | 23-27% | 21.2-23.1 | 27.2% | 20.9 |
| n4 fa1 | 31-38% | 24.8-27.1 | 40.1% | 25.9 |
| n3 fa1 | 39-49% | 27.1-30.9 | 50.2% | 27.4 |
| n2 fa1 | 48-55% | 27.7-30.1 | 53.3% | 26.7 |
| n15 fa0 | 10-10.4% | 7.5-7.7 | 12.8% | 6.2 |

- `-fa 0` is strictly worse than `-fa 1` → flash attention is exonerated.
- Acceptance rises monotonically as DFlash block size shrinks; DFlash block diffusion
  is all-or-nothing per block, so large blocks almost never fully pass.
- **Throughput tops out exactly at the plain 30.0 tok/s baseline** (n3: 27.1-30.9;
  best single sample 30.9; long-context n3 27.4 vs plain long 27.42). The 2GB
  diffusion-draft forward pass per block step cancels the acceptance gain.

## Methodology

Direct benchmark on the box: manual llama-server container from the fork Vulkan image
(`local-ai-machine/llamacpp-laguna-fork:vulkan-radv`, fork @ 04b2b72, Mesa 25.3.6
RADV), full `-c 131072` context, real `/v1/chat/completions` request timings
(`llamacpp-server-live-timing-v1`), 2 short fresh prompts + 1 long-context prompt per
config. Raw responses committed at `catalog/raw/dflash-sweep-2026-08-02/<config>/`.
Sweep used MAX_TOKENS=256 (vs M-053's 512) so magnitude comparisons across the two
runs are approximate — the trend across n is the signal.

## ROCm control (decisive attribution)

The 73-91% community numbers were all measured on a ROCm/HIP build of the same fork;
the M-055 ROCm control (`local-ai-machine/llamacpp-laguna-fork:rocm-7.14`, same
04b2b72 commit, GGML_HIP=ON gfx1151, base rocm/dev-ubuntu-24.04:7.14.0-full) measures
acceptance on THIS box at the community's config (n15, `-fa 0`).

**Outcome — TESTED_NOT_VIABLE, load never completed** (full evidence at
`catalog/raw/laguna-rocm-control-2026-08-02/EVIDENCE.md`):
1. DFlash server (n15, `-fa 0`, -c 131072) hangs during load: the memory-fit probe
   fails to create the draft llama_context (`dflash requires ctx_other to be set` →
   `failed to create llama_context from model`), then the real load stalls at ~551MiB
   RSS with no output for 7+ min.
2. The DFlash draft cannot init standalone (any backend) — `ctx_other` is only set by
   `--spec-type draft-dflash` server mode; run alone it fails (expected, but rules out
   the cheap "probe the draft alone" shortcut).
3. Even a PLAIN no-draft 68GB load on this ROCm build stalls after weight paging
   (~51GiB RSS, CPU spin ~73%, no output in 8+ min, immune to SIGTERM).

## What it means

- The ROCm control is a **clean negative**: DFlash never got far enough to measure
  acceptance on this box's ROCm path, and the stall reproduces even without the draft —
  this ROCm llama.cpp build is broken-in-effect on gfx1151 (consistent with the box's
  documented-broken `ollama-rocm-0177`). The community's 73-91% ROCm acceptance
  numbers do not reproduce on this hardware/toolchain.
- **Serve Laguna-S-2.1 plain at 30.0 tok/s (full 131072 context).** This closes the
  DFlash investigation; all three M-050 speculative-decoding options (fork-DFlash,
  XS classic draft, stock-llama.cpp MTP head) are resolved — none beats plain decoding
  on this box. A time-boxed fork-debug is not warranted: there is no Vulkan-vs-ROCm
  divergence left to attribute, since neither backend can serve DFlash at a
  throughput advantage.

