---
id: 2026-07-24-benchmark-orchestrator-canaries
date: 2026-07-24
source: "HANDOFF.md (\"Decisions made this session\", lines 185-271)"
tags: [benchmark, orchestrator, vllm, llamacpp, bug, tool-calling]
status: active
---

# Benchmark orchestrator canary runs: both completed end-to-end, real bugs found and fixed, one flagged not silently patched

**Canary 1 (`qwen3-coder-next-gptq4bit--vllm-therock-gfx1151-v1`), ~96 minutes wall-clock
for all 6 speed trials + coding harness — real results committed.** Two more real issues
surfaced, one fixed, one deliberately left for a human decision:

- **Fixed**: footprint fields were all `null` in committed data. Root cause: the
  orchestrator captured the vLLM startup log only after all 6 speed trials finished — the
  one-time "Model loading took..." / "GPU KV cache size..." lines had been pushed
  completely out of even a 400-line tail by then. Fixed by moving the capture to
  immediately after the health check, before any trial traffic. Canary 1's already-
  committed entry was not re-run to backfill this; the fix only affects future runs.
- **Fixed**: `resume_downloads()`'s `systemctl start` call hung the whole orchestrator.
  These are `Type=oneshot` units with no `RemainAfterExit`, so a plain `systemctl start`
  blocks the client until `ExecStart` exits — for a multi-hour download that's effectively
  forever. A responsiveness bug, not a safety bug (downloads were correctly resuming in
  the background the whole time). Fixed with `--no-block`.
- **NOT silently fixed — flagged for human review**: Tier B (tool-calling) scored 0/5 for
  this candidate, every task failing with `HTTP Error 400`. Root cause: this build's
  `build_specific_flags` never included `--enable-auto-tool-choice
  --tool-call-parser qwen3_coder` — only `--gpu-memory-utilization` and `--max-model-len`
  were present, so vLLM correctly rejected every request with a `tools=[...]` payload. A
  sibling build (same model family) uses the flags that are probably the right fix, but
  that's a build-file content edit judged to need human confirmation, not something to
  silently guess into the swap-in flag list. **This is a genuine, real judgment call on
  where to draw the line between "resolve and move forward" (see the Tier J max_tokens
  bump, which *was* auto-resolved) and "flag for a human"** — the distinguishing factor
  here was that fixing it meant guessing production-affecting serve flags for a specific
  model, not adjusting a test harness parameter.

**Canary 2 (`qwen3.6-27b--llamacpp-vulkan-radv-v1`), ~52 minutes — one real bug found and
fixed mid-run.** The coding harness's 1800s (30min) wrapper timeout was much too short for
a slow llama.cpp backend (~12.5 tok/s tg128); `seven-tier-coding-v2`'s own `timeout_s:
1500` is a per-request budget inside the harness, not a whole-harness one, and 22+ tasks
genuinely needed well over 30 minutes at that decode speed. First attempt hit a
`subprocess.TimeoutExpired`, silently producing zero data — but failure handling itself
worked correctly (clean teardown, vLLM restored, downloads resumed, no corrupted state).
Bumped the wrapper timeout to 3h (also llama-bench to 1h, vLLM per-trial timeout to
40min). Re-ran clean: llama-bench (344.83±14.49 pp512, 12.77±0.02 tg128, consistent with
earlier reference numbers) + full coding harness (19/22 across all 7 tiers). Also fixed a
small cosmetic bug found while reviewing the committed data: `yaml.safe_dump` without
`allow_unicode=True` backslash-escapes the "±" character (re-parses identically, just
harder for a human to read).

**Recommendation at the time (both canaries complete)**: ready for Phase 2, pending
explicit review/go-ahead per the standing risk-control plan — this task was scoped to
stop here regardless of how clean the canaries came out. The one item needing explicit
attention before a full unattended pass: the qwen3-coder-next-gptq4bit missing-tool-
parser-flags gap — either fix the build file's flags (accepting it'll re-run under Phase
2) or explicitly accept the misleading Tier B 0/5 as known-bad data to revisit later.
