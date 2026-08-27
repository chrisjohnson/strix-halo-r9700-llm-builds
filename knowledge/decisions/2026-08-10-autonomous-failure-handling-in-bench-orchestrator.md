---
id: 2026-08-10-autonomous-failure-handling-in-bench-orchestrator
date: 2026-08-10
source: M-106 session — Chris: "handle failures in the script, not via agentic intervention"
tags: [benchmark, orchestrator, watchdog, failure-handling, m-106]
status: active
---

# Autonomous failure handling in the llm-inference-bench orchestrator

**Decision**: the headless sweep's failure paths are handled by the orchestrator
(`app/orchestrator.py`) and watchdog (`watchdog.py`) themselves, not by an agent. Three
changes landed (commits `da157d2`, `45af863`):

1. **Known-failed fail-fast.** Builds whose `builds/<build>/build.yaml` status is
   `BROKEN` or `TESTED_NOT_VIABLE` are marked failed in seconds with the recorded
   reason, before compose up / health-wait. Proven live: laguna rocm-dflash (run 82)
   and laguna speculative-dflash (run 84) both failed instantly instead of burning
   the 20-min health-wait.
2. **Launch-failure classification.** When a health-wait times out, the container's
   tail logs are scanned for signatures (OOM, device-lost, nvfp4-unsupported,
   missing-model-file, import-error, kv-cap, server-up-probe-mismatch) and a
   `-failure.md` record is committed to git with the WHY. Proven live: ds4
   non-imatrix (run 83) auto-classified `missing-model-file` because its weights had
   been deleted.
3. **Stale-running orphan close.** New `POST /runs/{id}/close` endpoint; the watchdog
   closes runs left `running` that the worker can never resume (it only advances
   `queued`), including the M-106 run-66 case — a stale `active` run with no queued
   work. All 5 orphans (24/29/30/66/77) were closed automatically; sweep now ends
   with `stale-running-leftover=0`.

Also added `bench.timeout_s` per-build override for slow builds (the laguna-rocm
2-hour-timeout case).

**Why**: Chris's stated goal for M-106 — the sweep must arrive back "every model build
benchmarked or explicitly marked failed" with the process handling failures as it
encounters them, no agentic intervention. The previous sweep reached a terminal state
only because an agent (me) diagnosed 30 failed runs manually and wrote knowledge files
about each failure. The diagnosis logic and the orphan-reconciliation step are now
code.

**Alternatives considered**:
- Agent-driven post-run triage (status quo, M-106 up to now). Rejected: doesn't scale
  to unattended sweeps and loses the WHY if the agent doesn't look.
- A `PATCH /runs/{id}` endpoint. Rejected in favor of a purpose-built `POST
  /runs/{id}/close` that is idempotent and marks every non-terminal per-build failed
  atomically — no way for a caller to half-update state.

**Known limitation (open follow-up)**: `llm_decode_bench.py` auto-assumes the SGLang
engine and sends SGLang-shaped requests to the OpenAI-compatible endpoint, so every
ollama target produces "No completions". The engine-detection problem is out of scope
for M-106; a per-build `bench.engine` override is the planned fix.
