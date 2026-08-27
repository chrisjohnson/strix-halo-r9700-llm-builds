# knowledge/decisions/

One file per concrete decision made on this project: a choice among real alternatives,
with a stated reason. If nothing was actually chosen — just a fact discovered or a number
measured — it probably belongs in `knowledge/research/` instead. If it's a standing
policy or current state rather than a one-time choice, it probably belongs in
`knowledge/context/`.

## Filename

`YYYY-MM-DD-<slug>.md` — date the decision was made, then a short hyphenated slug
describing it (e.g. `2026-07-23-adopt-non-eager-awq-122b.md`).

## Frontmatter

```yaml
---
id: 2026-07-23-adopt-non-eager-awq-122b
date: 2026-07-23
source: README.md (Decision Log — 2026-07-23 later still, Phase 3 optimization)
tags: [vllm, awq, config-default]
status: active
---
```

See `knowledge/README.md` for the full field definitions (`id`, `date`, `source`, `tags`,
`status`).

## Body format

Each file should cover, in whatever prose/structure fits the content:

- **What was decided.** State the actual choice plainly, up front.
- **Why.** The reasoning or evidence that drove it.
- **Alternatives considered**, if any were — and why they weren't chosen.
- **Source.** Restate in the body (not just frontmatter) which original file/section this
  was migrated from, or what session/conversation produced it if new.

## Example

```markdown
---
id: 2026-07-23-adopt-non-eager-awq-122b
date: 2026-07-23
source: README.md (Decision Log — 2026-07-23 later still, Phase 3 optimization)
tags: [vllm, awq, config-default]
status: active
---

# Adopt non-`enforce-eager` as the standing default for the 122B AWQ tier

**Decision**: when swapping in `Qwen3.5-122B-A10B-AWQ-4bit`, do not pass
`--enforce-eager`. `VLLM_USE_TRITON_AWQ=1` is still required (separate, real AWQ-kernel
dependency, unrelated to eager mode).

**Why**: benchmarked head-to-head against the enforce-eager baseline. Removing
`enforce-eager` improved every metric by 1-9% (e.g. c8 output tok/s 16.05 -> 16.28) with
no regression anywhere. The original hypothesis — that `enforce-eager` was the main
driver of this model's poor concurrency scaling — turned out to be only marginally true;
the model's underlying slowness at this size/hardware combination is the bigger factor.

**Alternatives considered**: keeping `enforce-eager` (the prior default, chosen without
this comparison having been run). Rejected once the comparison showed no benefit and a
real, if small, cost.

**Tradeoff accepted**: slower cold start (~410s vs ~350s) from CUDA graph capture at
startup — accepted since this model stays loaded once served, and swap-in frequency
during benchmarking was judged a lesser cost than steady-state throughput.
```
