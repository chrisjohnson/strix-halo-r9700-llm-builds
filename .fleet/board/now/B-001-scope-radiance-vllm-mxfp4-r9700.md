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
1. [x] Research `codeberg.org/ggz14/radiance-vllm-mxfp4` for real: what
   base image/ROCm version it requires, whether gfx1201 is natively
   supported or needs an override, build instructions (source build vs
   prebuilt image), and how mature/recent the project is (commit
   history, open issues, single-maintainer risk).
2. [x] Cross-check against our box's actual current state (read-only):
   ROCm/driver version, kernel version, disk headroom for another
   image build — via `ssh local-ai-machine`, no changes.
3. [x] Identify what a real build attempt would require: does it need
   a source build (compile time, toolchain deps) or is there a
   prebuilt image; does it need its own MXFP4-quantized copy of
   Qwen3.8-27B (a new download) or can it consume something we already
   have.
4. [x] Write up a clear go/no-go recommendation for Chris — see
   Decision log/Handoff notes. **Recommendation: GO**, pending Chris's
   explicit go-ahead on the actual build+download (new ~19-60GB of
   downloads, an experimental single-maintainer image).
5. [ ] If Chris confirms: follow this repo's own convention — any new
   Dockerfile/build script/compose file goes into a real commit in
   this repo (`docker/`, `scripts/`, `builds/<id>/`) and gets deployed
   to the box via its normal git-pull-based flow, never an ad hoc
   SSH-authored file. Not started — this card stops at scoping.

## Signals
<!-- signal: claude 2026-09-03T00:00Z — claiming, starting research pass -->
<!-- signal: claude 2026-09-03T00:20Z — scoping done, recommendation is GO, holding for Chris's go-ahead before any download/build -->

## Decision log
- 2026-09-03 (claude): first card ever on this repo's board — no prior
  ID convention existed, picked `B-001` (Builds) since `M-` is already
  local-ai-machine's own prefix. Created directly in now/ per fleet
  rules §2/§4a: this is work Chris just explicitly asked for, so his
  request is the promotion — no separate confirmation needed.
- 2026-09-03 (claude): scoping research complete (web research +
  read-only box checks only, no changes made). Key findings:
  - Repo is real, reachable, and actively maintained (last push
    2026-09-03, 0 open issues, all 30 closed issues/PRs same
    maintainer — single-maintainer, ~10 days old, "early dev,
    experimental... not production hardened" per its own README).
    Layered on `codeberg.org/StillDeadcode/vllm-radiance`, which
    publishes the actual base image (`stilldeadcode/vllm-radiance:0.9.3`)
    to Docker Hub — not a from-scratch build requirement; the launcher
    pulls this prebuilt image and compiles one small kernel lib
    (`libr4d`, pinned commit) at container start. Full from-source
    build is optional.
  - **gfx1201/RDNA4 is the explicit primary target**, not an assumed
    fit — "compiled for gfx1201 only," developed on 2x R9700. Opposite
    risk profile from our two prior `kyuz0/vllm-therock-gfx1151`
    failures (gfx1151-targeted, gfx1201 was our own assumption).
  - Single-GPU (our actual hardware) is an explicitly supported,
    documented path: card count auto-detected ("one card works, four
    work"), TP=1 listed as supported in the knob table.
  - Required checkpoint `amd/Qwen3.8-27B-Quark-AWQ-MXFP4` confirmed
    real and live on HuggingFace. It does NOT load as-is — a
    documented AMD Quark/vLLM checkpoint-metadata mismatch (MTP-head
    exclude-list) requires running a bundled rewrite script
    (`fp8_mtp.py`, ~15 min) first. Same failure *class* as our two
    prior QuarkConfig dead ends, but here it's a known, already-solved
    issue with a provided fix shipped in-repo — not an unreported
    blocker we'd hit cold. Also needs a ~2GB drafter checkpoint
    (`tcclaviger/Qwen3.8-27B-DFlash2-FP8`) for its default
    speculative-decoding path, skippable via `--no-drafter`.
  - Box has plenty of headroom: ROCm-SMI-LIB 7.8.0, kernel 6.18.39,
    901GB free on root (repo wants ~60GB total: 19GB source, 19GB
    rewritten checkpoint, 2GB drafter, ~10GB image). Docker present
    (29.6.1); repo prefers podman but says docker is "handled by the
    launcher, less exercised" — a real but minor path-not-taken risk.
  - All published performance numbers (including the 573 tok/s
    aggregate figure matching the Reddit post) are 2-GPU tensor-
    parallel. No single-GPU numbers published anywhere found, and no
    independent (non-maintainer) reproduction found at all. Real
    single-R9700 throughput is genuinely unverified — likely well
    under 280 tok/s (no cross-GPU aggregation), though the MXFP4/W4A8
    kernel's per-GPU speedup claim (beating FP8) should still apply.

## Handoff notes
**Recommendation: worth an actual attempt — materially different risk
profile than our two prior vLLM dead ends.** gfx1201 support here is
first-class and tested (not an assumption on unrelated hardware), the
known checkpoint-loading pitfall already has a documented, shipped
fix, TP=1/single-GPU is an explicitly supported path, and disk space
is a non-issue (901GB free vs. ~60GB needed).

Real residual risks going in eyes-open: single-maintainer/10-day-old
project with zero independent reproduction; every published
performance number is 2-GPU TP, so actual single-R9700 throughput is
unverified and probably well below the 280 tok/s headline; docker (our
path) is explicitly the less-exercised runtime vs. the repo's
preferred podman.

**Holding here — not starting the download/build without Chris's
explicit go-ahead** (this is a new ~19-60GB download plus an
experimental, unproven-on-our-hardware image, not a routine
config change). If he confirms: next step is `setup-mxfp4.sh` per the
repo's own launcher flow, with any new Dockerfile/script/compose
committed to this repo first (per this repo's established
git-then-deploy convention), not ad hoc on the box.
