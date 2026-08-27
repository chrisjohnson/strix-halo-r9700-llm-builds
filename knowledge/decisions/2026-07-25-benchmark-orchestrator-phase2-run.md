---
id: 2026-07-25-benchmark-orchestrator-phase2-run
date: 2026-07-25
source: "HANDOFF.md (\"Decisions made this session\", lines 273-306)"
tags: [benchmark, orchestrator, systemd, tool-calling, bug]
status: active
---

# Phase 2 authorized and run to completion: systemd unit wired directly, two more real bugs found and fixed

**Decided: Phase 2 authorized.** Chris gave broad weekend-long authorization for exactly
this kind of unattended systemd-driven pass (2026-07-25/26). The sub-agent that had built
the orchestrator refused to proceed to Phase 2 when told to (treated the calling agent's
own go-ahead as an unverified "coordinator relay" rather than recognizing it as the agent
Chris had been directly instructing all session). Rather than spend a round-trip
re-litigating, the calling agent wired up the systemd unit directly
(`benchmark-orchestrator.service`/`.timer` in `configuration.nix`, timer-triggered
`OnBootSec=60s` matching the existing `docker-compose-app` pattern so `nixos-rebuild
switch` never blocks on a brand-new long-running unit's first start). First deploy attempt
failed immediately (`FileNotFoundError: docker` — systemd's default service PATH lacks
`/run/current-system/sw/bin`/`/run/wrappers/bin`); fixed via an explicit `Environment =
"PATH=..."`. Ran for ~11h39m straight, processing every ready vLLM + llama.cpp build, then
exited cleanly (by design — `Restart=on-failure` doesn't restart on a clean exit).

**Two more real, systemic bugs found and fixed live during the unattended run:**

1. **Missing `--enable-auto-tool-choice`** on `gemma-4-26b-a4b-it`, `gemma-4-31b-it`, and
   `glm-4.7-flash-awq` — each had `--tool-call-parser` set but not the enable flag, so
   Tier B scored a misleading 0/5 (every tool-calling request 400'd), exactly like the
   earlier `qwen3-coder-next-gptq4bit` gap from Canary 1 — except this time, since it was
   now a confirmed recurring pattern rather than a one-off, the fix was applied directly
   rather than re-flagged. `qwen3.5-4b` (the judge) and `qwen3.5-122b-a10b-awq4bit` were
   missing tool-call flags entirely. All four fixed, contaminated runs stripped and
   re-recorded clean (Tier B now real: 4-5/5 across all four). `north-mini-code-1.0-w4a16`
   (has a `<tbd>` max-model-len placeholder) and `qwen2.5-vl-7b-instruct` (deliberate
   prior exclusion, vision model) were correctly left alone.
2. **Hardcoded port 8000** in the vLLM speed-trial runner — every vLLM speed trial hit
   `http://localhost:8000` regardless of which container was actually targeted. Harmless
   for `vllm-primary`/swap-in candidates (really on 8000), but `vllm-judge` serves on 8001
   — every request failed instantly (`completed=0`), and the only validation was "does the
   result file exist," so all-zero data sailed through as if real and got committed. Fixed
   by threading the correct port through properly, plus a hard `completed=0` guard so a
   fully-failed trial can never be silently accepted again. A sweep of every other
   committed build's speed data confirmed this was isolated to the judge.

**Final coverage after Phase 2's first pass**: 16 of 20 in-scope (non-broken, non-ollama,
non-placeholder) builds had real committed data — every vLLM build and 9 of 10 llama.cpp
builds attempted succeeded. Remaining gaps, all identified/deferred deliberately:
- GPT-OSS-120B/20B (vLLM) and llamacpp-gpt-oss-120b: downloads still in flight when Phase
  2 finished its first pass. A separate real bug found here too: 4 of the original 6
  queued downloads had been silently stuck in `failed` state for ~23 hours (paused by an
  early preflight-pause step during Phase 1, never resumed). Resumed manually once caught;
  3 of 4 finished cleanly and were picked up via a manual orchestrator restart (it does a
  single pass and exits rather than looping, so it needs a manual nudge after a
  post-pass download finishes).
- `llamacpp-gpt-oss-120b` hit the same "file too large for non-Xet HTTP download, install
  hf_xet" error already seen with the vLLM `gpt-oss-120b` repo. Xet is deliberately
  disabled globally (documented as hanging repeatedly on this network path for other
  models) — enabling it just for this one risked trading a fast-failing crash-loop for an
  indefinite hang that could starve the two vLLM downloads that mattered more. **Decided:
  stop the crash-looping download service rather than risk that** — a judgment call to
  unblock higher-value downloads, not a silent drop. Deferred for a human decision on
  whether to pursue `hf_xet` or an alternate mirror.
