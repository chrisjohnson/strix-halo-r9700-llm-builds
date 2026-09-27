---
id: 2026-09-27-two-model-topology-and-measured-configs
date: 2026-09-27
source: tuning work on local-ai-machine, 2026-09-27 — measurements in knowledge/research/2026-09-27-flashnext-occamy-256k-memory-budget.md, -flashnext-flag-sweep.md, -flashnext-incremental-prefill-and-prompt-cache.md, -flashnext-decode-vs-context.md, -prefill-bench-padding-trap.md
tags: [topology, qwen3.8-flash-next, occamy, dirk, r9700, strix-halo, kv-cache, hipblaslt, standing-set]
status: active
---

# Two-model topology: flash-next on the APU, occamy on the R9700, with these exact configs

**Decision (a recommendation, not an adopted change)**: run qwen3.8-flash-next on the Strix
Halo APU and occamy on the R9700 eGPU, both at the model's full 262144 context, as:

| | build | key config |
|---|---|---|
| smart | `...-strixhalo-mtp-v2` | `ROCBLAS_USE_HIPBLASLT=1`; `--parallel 1`; `--cache-ram` left at its 8192 MiB default |
| fast | `occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2` | `-ctk q4_0 -ctv q4_0`; `-np 3 --kv-unified --kv-unified-per-slot 262144`; `-dev Vulkan0` |

**Authority**: this is what the measurements support. It is *not* applied. Adopting it means
either changing `local-ai-machine`'s `standing-models.txt` or repointing litellm roles, and
this repo's AGENTS.md puts both squarely in Chris's hands ("the one thing that IS Chris's
call"). v1 of each build is untouched and still available.

**Why each choice, with the number behind it:**

- **occamy belongs on the R9700, not the APU.** The R9700 is a discrete card with its own
  32 GiB of GDDR6 - measured: dirk held 30.68 GiB of VRAM with a 4.8 MB process RSS, and the
  host memory no meminfo bucket accounts for matches the *APU's* GTT (77.1 GiB) rather than
  the R9700's usage. So occamy's weights and KV cost the APU's 124 GiB pool essentially
  nothing (~1.6 GiB of GTT), which is what makes running both models at full context feasible
  at all. The earlier "165-173 GiB against 124 GiB, it does not fit" was wrong because it
  added the R9700's workload to the APU's pool.
- **`q4_0` KV for occamy, not `q8_0`.** Measured: **+73.7% prefill at 8k and +51.9% at 32k**
  versus q8_0, from cutting a host GTT spill of 3.42 GiB down to 1.55 GiB. The KV cache is
  allocated last, so it is what spills, and it is touched on every token. This is the single
  largest win found in this work.
- **occamy at `-np 3`.** Swept: slots 1-3 fit, np 4 overcommits (total demand 33.64 GiB
  against 31.86 available) and puts it into the spill regime that cost v1 74%.
- **flash-next gets `ROCBLAS_USE_HIPBLASLT=1`.** Measured: **+4.6% to +9.5% prefill**, five
  monotonic points, largest at short context - the shape of a GEMM-library win against the
  constant per-token floor. Supported by this image's rocBLAS, not a guess.
- **flash-next stays at `--parallel 1`.** np 3 was tested and works, but costs ~10 GiB of the
  shared APU pool (available 37 -> 19 GiB during a ladder) and 6-9% at short contexts. The
  pool is the binding constraint and this same work measured how sharp that cliff is
  (`-ub 8192` reached 3 GiB available and lost 63%). Stability wins.
- **`--cache-ram` unchanged.** The 8192 MiB default is already enough: q8_0 KV is 13,056
  bytes/token, so a full 262144-token prefix is ~3.4 GiB.
- **dirk is superseded on the R9700.** It and occamy cannot coexist in 32 GiB. The stated
  goal was "the eGPU will be the same occamy model", so this is intended, but it is a real
  consequence: the `medium-dense` litellm role pointed at dirk is now dead.

**Alternatives considered**: (a) *Keep dirk on the R9700 and occamy on the APU* - rejected:
both cannot be at full context on the APU's pool, which is the whole problem. (b) *occamy at
`-np 1` to eliminate the last 1 GiB of spill* - rejected: measured at +0.9%/+0.4%, i.e.
nothing, for two-thirds of the slot count. (c) *flash-next at np 3 for "maximum cache"* -
rejected, see above; "maximum useful cache" has to mean cache that does not cost stability.
(d) *Port llama.cpp PR #29030 for the n-gram path* - rejected as the answer to this build's
costs; see the separate decision entry.

**What each model actually delivers now**, measured:

| | prefill | decode |
|---|---|---|
| flash-next (APU, 262144 ctx) | 404 tok/s at 5.8k -> 141.8 at 251k tokens, cold | 18.0 -> 11.7 tok/s from ctx 0 to 64k |
| occamy (R9700, 3x262144 slots) | ~1,260 tok/s at 9.4k, ~1,080 at 35k (v1); v2 is +52-74% on that | ~78-95 tok/s (noisy, see below) |

Two caveats that belong next to those numbers rather than in a footnote: the full-context
prefill figure is the **cold** case - with the prompt cache warm, growing a context by ~3.7k
tokens against a 53k prefix costs 15.8s, not 185s - and **decode on this box has an ~8-11%
run-to-run noise floor** that a fixed sampling seed does not remove, so decode differences
below that are not resolvable here.

**Source**: every number above is from a measurement recorded in this repo on 2026-09-27; the
per-finding notes are named in the frontmatter `source`. The topology itself came from the
request that started this work, and the initial plan for it - including the incorrect memory
arithmetic - came from the opencode session named in the padding-trap note.
