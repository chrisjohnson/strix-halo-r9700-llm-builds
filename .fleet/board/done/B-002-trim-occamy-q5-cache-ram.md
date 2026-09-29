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
3. [x] Committed + pushed this repo (`7f8c3fb`).
4. [x] Updated local-ai-machine's `standing-models.txt` to reference v2 instead of v1
   (`e519909`).
5. [x] Bumped local-ai-machine's flake.lock pin for this repo via `deploy.sh
   --update-input strix-halo-r9700-llm-builds` on the box, synced the resulting pin back
   to git since the box's deploy key is read-only (`77b42cf`).
6. [x] Swapped the live container: `modelctl down` v1 (clean stop/remove), `modelctl up
   --exclusive` v2.
7. [x] Verified: `docker inspect` confirms `--cache-ram 16384` on the running container,
   `/health` returns 200, `free -h` shows 21GiB available post-swap (vs. 0.08GiB at the
   incident's trough).

## Signals
<!-- signal: claude 2026-09-29T22:50Z — claiming, mid-flight from local-ai-machine's own M-158-equivalent investigation session -->
<!-- signal: claude 2026-09-29T23:20Z — done, v2 live and healthy on :8191, moving to done/ -->

## Decision log
- 2026-09-29: 16384 chosen over other values via explicit margin math against the box's
  real 124 GiB total and flash-next's confirmed-flat 85.75 GiB GTT footprint - see the
  knowledge/research writeup for the full breakdown. Not yet re-validated under a real
  cache-filling workload; flagged in build.yaml as a follow-up if either a hang recurs at
  smaller scale or cache-hit rates visibly suffer.
- 2026-09-29: swapped v1 -> v2 without sudo, as plain `chris` (docker-group member) via
  `modelctl` directly - chris's own sudo rules don't include a passwordless `modelctl`
  entry (that NOPASSWD rule is scoped to the `dsh` user only), but `modelctl` itself
  doesn't require root for a docker-group member.

## Handoff notes
v2 is live and standing in v1's place. Not yet re-validated under a real cache-filling
workload over hours/days - worth revisiting `--cache-ram` again if either a smaller-scale
hang recurs or cache-hit rates visibly suffer from the smaller cap. v1's build directory
is left in place (untouched), per this repo's own convention, for historical reference.
