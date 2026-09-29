---
id: B-002
title: Trim occamy-1.0-mtp-q5 R9700 build's --cache-ram after midnight OOM hang on local-ai-machine
initiative_id: null
claimed_by: claude
claimed_at: 2026-09-29T22:50:00Z
blocks: null
blocked_by: null
status: null
related_cards: []
---

# B-002 — Trim occamy-1.0-mtp-q5's --cache-ram after midnight OOM hang

## Context
local-ai-machine hung around 2026-09-29 04:15 UTC (~midnight Eastern). Root-caused via
Prometheus telemetry (see local-ai-machine's
`knowledge/research/2026-09-29-occamy-cache-ram-midnight-hang.md` for the full writeup):
occamy's `--cache-ram 32768` (a llama.cpp host-RAM prompt cache, separate from and
invisible to VRAM/GTT metrics) was actively filling/evicting right up to the crash, while
both GPUs' actual VRAM/GTT usage stayed completely flat the entire window — disproving
the initial hypothesis that occamy + the standing flash-next build don't coexist safely.
Chris's explicit call after seeing the margin math: "Trim it" to 16384, leaving ~12 GiB
of headroom against the APU build's fixed ~86 GiB GTT commitment.

## Plan
1. [x] New build `occamy-1.0-mtp-q5--llamacpp-vulkan-radv-r9700-mtp-v2` (this repo does
   not edit a committed build in place) - identical to v1 except `--cache-ram 32768 ->
   16384`. build.yaml/docker-compose.yaml/REPRODUCE.md all written.
2. [x] Wrote `knowledge/research/2026-09-29-occamy-cache-ram-midnight-hang.md` in
   local-ai-machine with the full incident (Prometheus queries, timeline, margin math).
3. [ ] Commit + push this repo (direct-push authorized, same as local-ai-machine).
4. [ ] Update local-ai-machine's `standing-models.txt` to reference v2 instead of v1.
5. [ ] Bump local-ai-machine's flake.lock pin for this repo (`deploy.sh --update-input
   strix-halo-r9700-llm-builds`) so v2's build directory is actually visible to modelctl.
6. [ ] Deploy + swap the live container: stop v1, bring up v2 via modelctl.
7. [ ] Verify v2 healthy on :8191, confirm via `/health` and a real request.

## Signals
<!-- signal: claude 2026-09-29T22:50Z — claiming, mid-flight from local-ai-machine's own M-158-equivalent investigation session -->

## Decision log
- 2026-09-29: 16384 chosen over other values via explicit margin math against the box's
  real 124 GiB total and flash-next's confirmed-flat 85.75 GiB GTT footprint - see the
  knowledge/research writeup for the full breakdown. Not yet re-validated under a real
  cache-filling workload; flagged in build.yaml as a follow-up if either a hang recurs at
  smaller scale or cache-hit rates visibly suffer.

## Handoff notes
(in progress - see Plan above for what's left)
