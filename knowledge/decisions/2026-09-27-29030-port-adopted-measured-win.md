---
id: 2026-09-27-29030-port-adopted-measured-win
date: 2026-09-27
source: measurement work on local-ai-machine, 2026-09-27 — the A/B is recorded in builds/qwen3.8-flash-next-iq4xs--llamacpp-rocm714-lazy-direct-strixhalo-mtp-v1/build.yaml; supersedes 2026-09-27-29030-port-deprioritised-measure-floor-first.md, which recommended against this and was wrong
tags: [qwen3.8-flash-next, prefill, performance, llama.cpp, lazy-mode, mmap, pr-29030, port, strix-halo]
status: active
---

# Port PR #29030 after all - it is worth +22% to +29%

**Decision**: port llama.cpp PR #29030 (direct-read lazy gather) into the EngramHalo fork,
build it, and promote it as
`qwen3.8-flash-next-iq4xs--llamacpp-rocm714-lazy-direct-strixhalo-mtp-v1`. It is the largest
single win found in this work and it supersedes v3 (+10.7-14.8% over v1) by another 22-29%.

**Authority**: a measured recommendation, not an adopted change. v1 still runs on 8152 and is
still what litellm's `big-moe` role points at. Adopting this is a deliberate engine swap -
repoint the role to 8178 or change the standing build - and standing-models.txt is Chris's
call per AGENTS.md.

**Why, with the numbers** - real-corpus prompts, single stream, server-reported timings:

| requested | tokens | v1 | v3 (both env vars) | port | vs v1 | vs v3 |
|---|---|---|---|---|---|---|
| 2k | 2,409 | 337 | 387 | **483** | +43.3% | +29.1% |
| 8k | 9,400 | 371 | 416 | **504** | +35.8% | +23.8% |
| 32k | 35,301 | 326 | 361 | **434** | +33.1% | +21.9% |

**Page-cache warmth was controlled, not assumed.** The port's first run was faster than its
own confirmation run, which is the signature of a warming cache rather than a real effect, so
v3 was stopped and re-measured on the same warm cache immediately afterwards: v3 gave
374/407/356 against its earlier 387/416/361 - no warm-up benefit - while the port gave
483/504/434. The advantage is real.

**Why the earlier recommendation was wrong**: it argued that the fork already implements
batched row prefetch (`prefetch_rows()`, present in the image) so the PR would add little.
That conflated two mechanisms. `prefetch_rows()` *queues mmap faults* for a gather that still
reads the mapping; PR #29030 *replaces the gather*, so it never touches the mapping at all.
The port was also far cheaper than the earlier entry implied: 19 of 21 files applied cleanly
and the rest were offsets and fuzz, not semantic conflicts.

**Alternatives considered**: (a) *Keep it deprioritised* - that was the prior entry, now
retracted. (b) *Rebase rather than vendor a patch* - the PR is still OPEN upstream, so a patch
is the only reproducible form today; it is vendored as
`docker/qwen4exp-strix-halo-mtp/llama-cpp-29030-lazy-direct.patch` with its own Dockerfile.
(c) *Drop the fork's per-buffer-mmap patch* - not a choice: PR #29030 and that patch both
rewrite `src/llama-model-loader.{cpp,h}` and are mutually exclusive. The upstream Dockerfile
already treats it as optional, so the build follows its documented fallback.

**The one open question**: this A/B measures "PR present, per-buffer-mmap patch absent"
against v3, which carries both. A control build with neither would isolate the PR alone. That
has not been done, and it is the only thing that could change the attribution - stated rather
than glossed.

**Operational consequence worth flagging**: the PR renames `--tensor-read-lazy` to
`--lazy-mode`, and `on` now means direct reads rather than mmap. There is no separate
`on-direct` value. Any build on the new image passing the old flag name will not start.
