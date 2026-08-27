---
id: 2026-07-24-llama-server-concurrent-serving-results
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"llama-server concurrent-serving benchmark, actually run\", lines 350-358)"
tags: [llamacpp, concurrency, vulkan, qwen, benchmark]
status: active
---

# llama-server concurrent-serving benchmark, actually run: correctness passed, real ~3x throughput gain

**Finding**: followed through on the concurrent-serving gap identified in
`2026-07-24-llama-server-concurrent-serving-gap-and-bugs.md` with a real benchmark, not
just research. Model: Qwen3.6-27B-Q4_K_M.gguf (dense, 26.90B params), `llama-server`
inside `kyuz0/amd-strix-halo-toolboxes:vulkan-radv`, `-np 4 -cb -kvu -c 32768` (4 parallel
slots, continuous batching, unified KV cache). `vllm-primary`/`vllm-judge` stopped and the
download queue paused first per the standard preflight.

**Correctness checked first**, given the real caveats flagged in the research pass (open
HIP/ROCm corruption bug, older unresolved RADV concurrent-slot-hang report). Fired 4
concurrent requests with clearly distinguishable prompts ("17*23?", "capital of France?",
"BANANA x5", "sky color?") — all 4 returned promptly (200 OK, ~17-22s each, genuinely
overlapping in wall-clock) with the objectively correct answer for their own prompt, and
each response's own reasoning trace stayed on-topic for its own question. No corruption,
no cross-contamination, no hang — the Vulkan/RADV backend held up cleanly, consistent
with the research pass's expectation.

**Throughput, measured only after correctness passed**: c1 (single request) generated at
12.60 tok/s — closely matches the existing single-stream `llama-bench` tg128 baseline for
this file (12.75±0.03 tok/s), a good sanity check that `llama-server`'s continuous-batching
path behaves like plain decode under no concurrent load. c4 (4 simultaneous identical
long-form requests, 512 tokens each) sustained ~38.3-39.1 tok/s aggregate (~9.7-9.8 tok/s
per individual slot, confirmed both from response JSON timings and per-slot server log
lines showing all 4 slots decoding simultaneously) — a real ~3.0-3.1x aggregate throughput
gain over single-stream, at the cost of each individual request's wall-clock time growing
~27% (42.0s to 53.5s for the same 512-token completion) versus running alone.

**Significance**: the first concurrent-serving number for llama.cpp on this hardware —
every prior llama.cpp figure in this project was single-stream `llama-bench`. Loosely
comparable to vLLM's c1/c8 convention (c4 vs c8, not identical concurrency levels — a
future pass could push `-np 8` for a tighter comparison).
