---
id: B-001
title: Scope feasibility of radiance-vllm-mxfp4 (MXFP4 W4A8) on the R9700
initiative_id: null
claimed_by: claude
claimed_at: 2026-09-03T00:00:00Z
blocks: null
blocked_by: null
status: null
related_cards: []
---

# B-001 — Scope feasibility of radiance-vllm-mxfp4 (MXFP4 W4A8) on the R9700

## Context
Chris saw a Reddit post claiming 280 tok/s decode on Qwen3.8-27B across
2x R9700 (RDNA4/gfx1201) using a custom vLLM fork,
`codeberg.org/ggz14/radiance-vllm-mxfp4`, built on top of "DeadCode's
radiance image" with MXFP4 W4A8 kernels reportedly beating FP8 on this
hardware, plus "DFlash2" speculative decoding.

Checked our own real state before recommending anything (previous pass
in this conversation wrongly used a stale `local-ai-machine/catalog`
checkout — corrected):
- **DFlash2 already tried on our R9700** with this exact model
  (`qwen3.8-27b-q4km-dflash2--llamacpp-dflash2-vulkan-radv-r9700-v1`):
  `TESTED_NOT_VIABLE`, 27-36 tok/s vs the existing native-MTP build's
  41-52 tok/s. Not worth revisiting without a specific new reason.
- **vLLM on this box is 0-for-2 for Qwen3.8-27B**: AutoRound quant
  (unsupported on ROCm) and AMD Quark AWQ-INT4 (real, unreported crash
  in `QuarkConfig.apply_vllm_mapper()`) — both via
  `kyuz0/vllm-therock-gfx1151`, both hard dead ends unrelated to
  tuning, before any benchmark ever ran.
- Current standing medium-dense endpoint:
  `qwen3.8-27b-q6kl--llamacpp-vulkan-radv-r9700-mtp-v1` (Q6_K_L, native
  MTP, full 262144 ctx) — ~35 tok/s solo decode, ~104 tok/s prefill.
  Single R9700 only (no tensor-parallel — the post's 280 tok/s leans on
  2 cards).

So the only genuinely untested lever from that post is the MXFP4
kernel fork itself — a different image/maintainer than either failed
vLLM attempt, but the same general risk class (obscure prebuilt/
source-built vLLM-ROCm stack) that's already burned real time twice.
This card is a **scoping pass only** — does this even build/run on our
gfx1201 card at all — before committing to a real build+benchmark
attempt.

## Plan
1. [ ] Research `codeberg.org/ggz14/radiance-vllm-mxfp4` for real: what
   base image/ROCm version it requires, whether gfx1201 is natively
   supported or needs an override, build instructions (source build vs
   prebuilt image), and how mature/recent the project is (commit
   history, open issues, single-maintainer risk).
2. [ ] Cross-check against our box's actual current state (read-only):
   ROCm/driver version, kernel version, disk headroom for another
   image build — via `ssh local-ai-machine`, no changes.
3. [ ] Identify what a real build attempt would require: does it need
   a source build (compile time, toolchain deps) or is there a
   prebuilt image; does it need its own MXFP4-quantized copy of
   Qwen3.8-27B (a new download) or can it consume something we already
   have.
4. [ ] Write up a clear go/no-go recommendation for Chris: plausible
   build path + rough effort/risk, or a specific blocking reason not
   to bother (e.g. abandoned project, hard gfx1201 incompatibility,
   requires a ROCm version that conflicts with what's already
   installed).
5. [ ] If go: follow this repo's own convention — any new
   Dockerfile/build script/compose file goes into a real commit in
   this repo (`docker/`, `scripts/`, `builds/<id>/`) and gets deployed
   to the box via its normal git-pull-based flow, never an ad hoc
   SSH-authored file. No infra changes yet in this scoping pass.

## Signals
<!-- signal: claude 2026-09-03T00:00Z — claiming, starting research pass -->

## Decision log
- 2026-09-03 (claude): first card ever on this repo's board — no prior
  ID convention existed, picked `B-001` (Builds) since `M-` is already
  local-ai-machine's own prefix. Created directly in now/ per fleet
  rules §2/§4a: this is work Chris just explicitly asked for, so his
  request is the promotion — no separate confirmation needed.

## Handoff notes
Scoping only — do not start an actual build/download without a
reviewed go/no-go writeup in this card first.
