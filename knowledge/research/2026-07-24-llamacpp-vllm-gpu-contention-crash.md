---
id: 2026-07-24-llamacpp-vllm-gpu-contention-crash
date: 2026-07-24
source: "HANDOFF.md (\"Smoke testing (this session's last activity)\", llama.cpp path paragraph)"
tags: [gpu-contention, llamacpp, vllm, ollama, stability, crash, benchmark-harness]
status: active
---

# llama.cpp/Ollama + resident vLLM services: confirmed GPU-memory-contention crash

**Finding**: running `llama-server` (a GGUF load) concurrently with `vllm-primary` and
`vllm-judge` resident on the GPU causes real, reproducible crashes, not harness bugs.
During a 7-tier coding-benchmark smoke test, every llama.cpp-path task failed; the cause
looked at first like a harness problem but was actually GPU memory contention —
confirmed twice, with `RestartCount` climbing to 4 and 3 respectively on the two
resident vLLM containers.

**Fix / standing procedure**: stop the resident vLLM services *before* starting any
llama.cpp (or Ollama) benchmark run — `docker compose stop vllm-primary vllm-judge` (or
the equivalent current service names) from `~/local-ai-machine/docker`. This is exactly
what `catalog/OPERATIONS.md`'s preflight/teardown procedure already documents; this
incident is a real, concrete confirmation of why that step is mandatory, not optional —
it was skipped once for convenience during this smoke test and failed twice as a
result.

**Scope**: the Ollama path was not attempted in this session at all, but the same
GPU-contention risk applies — stop resident vLLM services first there too.

**Not to be confused with the separate, looser bandwidth-contention allowance**: Chris
explicitly said concurrent *downloads* are fine to run during smoke/dev testing (not the
real recorded benchmark pass) — that only affects prompt-processing (PP) throughput
numbers, a data-quality concern, not a stability one. Don't extend that same looseness to
this GPU-contention issue — it's a real crash risk, not just noisier numbers.
