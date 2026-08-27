# knowledge/research/

One file per discrete research finding or benchmark result: something investigated or
measured, whether or not it directly produced a decision. Benchmark numbers, hardware/
software compatibility findings, third-party tool evaluations, verification of claims
from external sources — all belong here. If the finding directly led to a specific choice
being made, it's fine (and often useful) for a `knowledge/decisions/` file to reference it
back by `id`, but the finding itself still lives here, not there.

## Filename

`YYYY-MM-DD-<slug>.md` — date the finding was produced or verified (not the date it was
migrated into this directory), then a short hyphenated slug (e.g.
`2026-07-24-fastflowlm-and-mtp-confirmed.md`).

## Frontmatter

```yaml
---
id: 2026-07-24-fastflowlm-and-mtp-confirmed
date: 2026-07-24
source: OPTIMIZATIONS.md ("Second deep-dive pass: FastFlowLM and confirmed-working MTP", lines 119-129)
tags: [mtp, llamacpp, speculative-decoding, qwen, benchmark]
status: active
---
```

See `knowledge/README.md` for the full field definitions (`id`, `date`, `source`, `tags`,
`status`). `status: superseded` matters more here than elsewhere — benchmark numbers and
compatibility findings age, especially anything tied to a specific software version; mark
a file superseded (and point to its replacement) rather than editing old numbers in place.

## Body format

Each file should cover:

- **The finding.** What was found or measured, stated plainly.
- **Methodology / source.** How it was produced — a direct benchmark run (command, model,
  hardware), a verified external source (a fetched doc, an upstream issue, a dataset), or
  an explicitly-flagged lower-confidence source (e.g. an unverified forum post) if that's
  all that was available. Say which, honestly — confidence level is part of the finding.
- **Date.** When the measurement/verification happened.
- **Tags** that make the finding groupable across files (backend/engine names, model
  families, hardware, technique).

## Example

```markdown
---
id: 2026-07-22-qwen35-122b-vllm-speed
date: 2026-07-22
source: README.md (Decision Log — 2026-07-22, Benchmark pass)
tags: [vllm, awq, benchmark, qwen]
status: active
---

# Qwen3.5-122B-A10B-AWQ-4bit: vLLM speed benchmark

**Finding**: at concurrency 1, this model generates 7.87 tok/s with far more consistent
latency than the alternatives tested in the same pass; at concurrency 8, 16.05 tok/s,
slowest of the three models compared (35B bf16 primary and an 80B GPTQ model were also
in this pass — see `docs/benchmark-report-2026-07-22.html` for the full table).

A separate, counterintuitive footprint finding from the same pass: this 122B model is
*smaller on disk* and leaves *more KV cache headroom* than the 35B bf16 model (46.49GiB
weights / 40.42GiB KV vs. 66.97GiB weights / 18.49GiB KV) — quantization beat raw
parameter count for memory footprint here.

**Methodology**: `vllm bench serve`, concurrency 1 and 8, run as a temporary swap-in (not
concurrent with the standing primary), full write-up in
`docs/benchmark-report-2026-07-22.html`.
```
