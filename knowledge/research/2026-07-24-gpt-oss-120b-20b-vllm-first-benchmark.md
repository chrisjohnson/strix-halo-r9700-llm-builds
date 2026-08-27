---
id: 2026-07-24-gpt-oss-120b-20b-vllm-first-benchmark
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"GPT-OSS-120B and GPT-OSS-20B benchmarked via vLLM\", lines 360-380)"
tags: [gpt-oss, vllm, moe, benchmark, harmony, tool-calling]
status: active
---

# GPT-OSS-120B and GPT-OSS-20B: first vLLM benchmark, closing the highest-confidence-candidate loop

**Finding**: both models had fully downloaded weight content but had never been served in
any form on this machine before this pass. Benchmarked sequentially, one at a time, full
GPU dedicated to each.

**Real methodology problem found and fixed**: GPT-OSS's harmony chat format is
incompatible with the project's standard `--ignore-eos` speed-benchmark recipe. The
standard `vllm bench serve --backend openai-chat --endpoint /v1/chat/completions
--ignore-eos` invocation fails 100% of the time against GPT-OSS — forcing generation past
the model's natural end-of-turn token violates the harmony format's expected token
grammar, throwing `openai_harmony.HarmonyError: Unexpected token 200002 while expecting
start token 200006` on every request. Confirmed independently via manual curl. **Fix**:
switched to `--backend openai --endpoint /v1/completions` (bypasses the chat
template/harmony parser entirely) — same random-dataset/prompt-count convention as every
other model, just a different backend/endpoint pair for this one model family.

**GPT-OSS-120B results**: c1 8.46 tok/s output, c8 31.39 tok/s output. Footprint: 68.7 GiB
weights, 41.31 GiB KV cache, 8.63x max concurrency @131072. Cold start ~220s. Six-tier
coding harness: 11/12 — the best coding-harness score of any model tested in this project
at the time (only Tier J's `judge_incorrect` task failed, a recurring miss shared with
other models). **Somewhat surprising finding**: 120B's c1 throughput is notably slow for a
~5.1B-active-param MoE model on this hardware — behind every other small-active-param MoE
model tested (Qwen3.6-35B-A3B 11.91, Gemma-4-26B-A4B-it 20.85, GLM-4.7-Flash-AWQ 18.95, all
c1). Plausible-but-unconfirmed hypothesis: this build's MXFP4 MoE kernel path may not be a
fully optimized low-bit matmul on gfx1151 (no native FP4 matrix-core hardware on
RDNA3.5) — not confirmed via kernel profiling, flagged as a hypothesis.

**GPT-OSS-20B results**: cold start under 2 minutes. c1 12.59 tok/s output, c8 56.72
tok/s output — the fastest c8 throughput of any coding-comparison-lineup model tested at
the time, beating Gemma-4-26B-A4B-it's previous best (50.38). Footprint: 14.16 GiB
weights, 95.81 GiB KV cache, 30.02x max concurrency @131072 — the best concurrency
headroom of any model tested at the time. Six-tier coding harness: 10/12 (Tier B failed
`multi_step_tool_call`, Tier J failed `judge_incorrect` and produced no valid JSON
verdict).

**Active-param-size pattern holds, with a real nuance**: 20B performs completely normally
for its size class despite using the identical MXFP4 format and parser stack as 120B —
real evidence against "MXFP4 is just slow on this hardware" as a blanket explanation,
pointing instead toward 120B's much larger expert pool (128 experts vs. 20B's smaller
pool) hitting the memory-bandwidth ceiling harder, independent of quantization format.
