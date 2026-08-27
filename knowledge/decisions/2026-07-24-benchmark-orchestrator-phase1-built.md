---
id: 2026-07-24-benchmark-orchestrator-phase1-built
date: 2026-07-24
source: "HANDOFF.md (\"Decisions made this session\", lines 163-184)"
tags: [benchmark, orchestrator, automation, script]
status: active
---

# Build a resumable benchmark orchestrator (Phase 1 of 2), deliberately not yet wired to run unattended

**Decided**: build `scripts/benchmark_orchestrator.py` implementing everything in
`catalog/OPERATIONS.md`'s safety procedure programmatically — live `.download-complete`
marker checks (never trusting build-file notes/status text), preflight download-pause/
resume with correct unit-name parsing, vLLM standing-service-in-place vs. swap-in-
candidate handling, llama.cpp's two-separate-container-lifecycle pattern (llama-bench then
llama-server), a mandatory correctness gate before trusting
`llamacpp-server-concurrent-v1` throughput, full run-fingerprint capture, and YAML-surgery
appends to `benchmark_runs:` (never a full re-dump, so hand-written build-file formatting
survives). Supports `--dry-run` and `--only <build-id>`.

**Why deliberately not yet wired to a systemd unit / not run against the full build
matrix**: that step (Phase 2) was gated on review of two canary commits first — see
`2026-07-24-benchmark-orchestrator-canaries.md`.

**Real bug found and fixed by the first canary attempt**: `swap_model_start.sh`/
`swap_model_stop.sh` (plus `speed_benchmark_swap.sh`/`amdgpu-metrics.sh`) were committed
as mode 644 (non-executable) — harmless when invoked via `bash script.sh` but broke the
orchestrator's direct `subprocess.run([path, ...])` call with a real `Permission denied`.
Fixed via `chmod +x` + commit, not hand-patched on the box.

**Real drift found live during this task, confirming why the download-completeness check
must be live, not trusted from any snapshot**: a build file's own notes still said
"download actively in progress" but its `.download-complete` marker already existed on
the box — the orchestrator correctly picked it up as runnable rather than skipping it
based on stale prose.
