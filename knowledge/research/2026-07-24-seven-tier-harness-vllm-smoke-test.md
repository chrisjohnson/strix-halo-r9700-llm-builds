---
id: 2026-07-24-seven-tier-harness-vllm-smoke-test
date: 2026-07-24
source: "HANDOFF.md (\"Smoke testing (this session's last activity)\", vLLM-path paragraph and the informational-findings paragraph)"
tags: [harness, smoke-test, vllm, coding-benchmark, tier-j, tier-p, tier-q]
status: active
---

# 7-tier coding-benchmark harness (A/B/J/P/D/Q/L): first real smoke test, vLLM path

**Purpose**: verify the expanded `scripts/coding_benchmark.py` harness (7 tiers:
A/B/J/P/D/Q/L) actually works end-to-end against a real model, not just that the YAML
task definitions look right on paper.

**Result — vLLM path: fully validated.** Ran clean against `vllm-primary`
(`qwen3.6-35b-a3b`). Two real harness bugs were found and fixed in the same session
(committed at `3cd8b3a`):
- An uncaught `RemoteDisconnected` exception that crashed the whole harness mid-run
  (not model-specific — a real robustness gap in the harness's HTTP handling).
- A Tier J token-budget bug: the configured budget (2048 tokens) was too low and needed
  raising to 4096. Confirmed via evidence, not guesswork — the failing task ran 144.6s
  vs. 19-88s for every sibling task, with zero output, matching the exact
  reasoning-budget-exhaustion signature already seen and identified in Tiers A/B.

**Two informational (not bug) findings worth keeping in mind for future task design**:
- `structured_extraction` (Tier P) failed on a `#` prefix the task spec never explicitly
  says to strip — likely a task-specification ambiguity, not a model error.
- `planning_db_migration` (Tier Q) only hit 2 of 3 required topics — a real, if minor,
  result worth tracking if it recurs on other models.

**llama.cpp and Ollama paths were not validated in this smoke test** — see
[[2026-07-24-llamacpp-vllm-gpu-contention-crash]] for why (GPU memory contention with
resident vLLM services, not a harness problem).
