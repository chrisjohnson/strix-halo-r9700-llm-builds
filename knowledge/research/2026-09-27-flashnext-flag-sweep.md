---
id: 2026-09-27-flashnext-flag-sweep
date: 2026-09-27
source: direct A/B on local-ai-machine — throwaway llama-server instances on the Strix Halo APU, one variable each, real-corpus prompts via llm_decode_bench.py with server-reported timings
tags: [qwen3.8-flash-next, prefill, benchmark, hipblaslt, ubatch, tensor-read-lazy, strix-halo, memory, no-win]
status: active
---

# flash-next flag sweep: one win (HIPBLASLT), two levers that are memory-doomed

## Summary

Three single-variable A/Bs against build
`qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v1`, each as a throwaway container
on the APU with the real-corpus prompt set and the server's own `timings`. Prefill tok/s at
requested contexts 1k/2k/4k/8k/32k (actual tokens 1,437 / 2,408 / 5,072 / 9,399 / 35,300):

| variant | 1k | 2k | 4k | 8k | 32k |
|---|---|---|---|---|---|
| **v1 baseline** (`-ub 2048`, `--tensor-read-lazy on`) | 326 | 335 | 370 | 372 | 325 |
| **`ROCBLAS_USE_HIPBLASLT=1`** | **357** | **364** | **393** | **391** | **340** |
| delta | +9.5% | +8.7% | +6.2% | +5.1% | +4.6% |
| **`-ub 8192`** | 325 | 344 | 245 | 137 | 211 |
| delta | -0.3% | +2.7% | **-33.8%** | **-63.2%** | **-35.1%** |
| **`--tensor-read-lazy off`** | 111 | 122 | 172 | 228 | 283 |
| delta | **-66.0%** | **-63.6%** | **-53.5%** | **-38.7%** | **-12.9%** |

Only HIPBLASLT is a win. The other two are losses, and importantly they are **not compute
results** — both are the APU's memory budget being exceeded:

- `-ub 8192`: available memory fell to **3 GiB** once healthy. A larger ubatch needs much
  more compute scratch, and at ≥4k tokens the working set no longer fits. The 1k/2k points
  (where memory is not under pressure) are neutral-to-slightly-positive, which is the tell.
- `--tensor-read-lazy off`: makes the ~26.8 GiB n-gram/PLE tensor *resident* instead of
  demand-paged. Available memory stayed at 37 GiB (so it did not thrash the way `-ub 8192`
  did), and prefill still collapsed — the resident table costs the same pool the dense
  weights and KV need. The deficit shrinks with context (-66% at 1k to -13% at 32k) because
  the constant per-token cost being lost matters less once attention dominates.

## What this means for the constant floor

`knowledge/research/2026-09-27-flashnext-prefill-constant-floor.md` fits a
context-independent **2.58 ms/token** floor and asks how much of it is the PLE gather. This
sweep does not answer that directly, but it rules out the cheap explanation on one side: the
lazy path is **worth having**, not a tax. Turning it off makes prefill far worse, so the
floor is not "mmap fault overhead on the lazy tensor" — if it were, removing the lazy
mechanism would have helped.

Combined with the storage-latency bound in that note (16 serialised cold row reads would cost
~3.2 ms/token, more than the entire floor), the consistent reading is that the gather is
cheap on this box and the floor is something else: the 36 SSM layers' state updates, MoE
routing across 512 experts, the context-independent share of the 12 full-attention layers'
projections, and KV writes. **None of those has a launch flag on this build**, which is why
the floor remains unattributed rather than unexamined.

## The one win is real and is promoted

`ROCBLAS_USE_HIPBLASLT=1` is supported by this image's rocBLAS
(`/opt/rocm/lib/librocblas.so.5.5` contains the literal, alongside `USE_HIPBLASLT_BATCHED`).
It has been promoted to build `...-strixhalo-mtp-v2`, which is `TESTED_VIABLE` and measured
as above. Note that the flag lives in rocBLAS, not in `llama-server`, so grepping the server
binary for it finds nothing — that is why one claim inherited from the earlier session about
this flag was true while its companion claim was not.

## Correction: `GGML_HIP_GDN_CHUNK` DOES exist - the earlier "refuted" claim was wrong

An earlier version of this note said this lever "does not exist in this build", on the
strength of a binary grep. **That was wrong and the claim is withdrawn.** The grep searched
`/usr/local/bin/llama-server`, which in this image is a **12 KB launcher shim** - the real
code lives in `/usr/local/lib64/libllama.so` and the `libggml-*.so` family. Grepping those
finds it immediately (3 occurrences of the literal), alongside 594 of `gated_delta`.

What it is, from `ggml/src/ggml-cuda/gated_delta_net.cu`:

```
// GDN_RDNA: RDNA3/RDNA4 run the same ggml_cuda_mma path with WMMA
// (v_wmma_f32_16x16x16_f16). Opt-in via GGML_HIP_GDN_CHUNK=1 until broadly
// benchmarked; ...
```

so it opts RDNA3/RDNA4 into the WMMA **chunked** GDN path that is otherwise admitted only
for NVIDIA Ampere+/CDNA. gfx1151 is RDNA 3.5, so this build is currently on the non-opted-in
path and the env var is a real, cheap, untested lever - on 36 of 48 layers. The earlier
session that flagged it as the lever the other agent missed was right, and this note said so
incorrectly for most of a day.

**Result (measured 2026-09-27, same session, same corpus and seed):** the lever is worth
it. `GGML_HIP_GDN_CHUNK=1` alone gives **+7.4% to +10.7% prefill**, and roughly *flat* across
context (1k: 326->350, 32k: 326->351) - the signature of a constant per-token cost, which is
what 36 of 48 GDN layers are. Combined with `ROCBLAS_USE_HIPBLASLT=1` the two are additive:
**+10.7% to +14.8% over v1**. Promoted as build `...-strixhalo-mtp-v3`.

| requested | tokens | v1 base | +HIPBLASLT | +GDN_CHUNK | both (v3) | v3 vs v1 |
|---|---|---|---|---|---|---|
| 1k | 1,437 | 326 | 357 | 350 | 366 | +12.3% |
| 2k | 2,408 | 337 | 364 | 373 | 387 | +14.8% |
| 4k | 5,072 | 370 | 393 | 401 | 414 | +11.9% |
| 8k | 9,399 | 371 | 391 | 403 | 416 | +12.1% |
| 32k | 35,300 | 326 | 340 | 351 | 361 | +10.7% |

**Method lesson, worth more than the flag:** `grep -c` counts *lines*, and a binary has
almost no newlines, so `grep -aoc PATTERN bigbinary` returns 0 or 1 almost regardless of the
answer - a false negative generator. Use `grep -ao PATTERN file | wc -l`, and make sure the
file is the code and not a shim (`ls -la` is the check; 12 KB is not a llama.cpp).


## Method

Each variant was its own `docker run` on the APU with build v1's exact command, changing one
thing, then the same
`llm_decode_bench.py --contexts 0 --concurrency 1 --prefill-contexts 1024,2048,4096,8192,32768
--prefill-repeats 1 --context-file <2.8 MB real corpus>` run against it. v1 was stopped for
each so only one flash-next instance used the APU. `free -g` and card1's GTT were read once
healthy, which is what identified the two losses as memory effects rather than compute ones
— read the tok/s table alone and `--tensor-read-lazy off` looks like a kernel regression
rather than the pool running out.

## Caveats

- One sample per point, `--prefill-repeats 1`. The HIPBLASLT gain is five monotonic points
  and is trusted; the two losses are large enough that sampling error is irrelevant to their
  sign, but their magnitudes are not precise.
- The memory readings are point-in-time once healthy, not peak during prefill.
- `-ub 4096` was not tested. Given 8192's failure is memory-driven, 4096 may be mildly
  positive or mildly negative; it is the one obvious gap.

## Addendum: more concurrent slots - feasible, but it spends the stability margin

The "maximum useful cache" half of this work's goal suggests raising flash-next's slot count
from the 1 it runs to match occamy's 3 (which has three 262144-token slots). Tested as a
throwaway with `-c 786432 --parallel 3`, which makes `n_ctx_slot` exactly 262144 - the model's
native limit - so no `--override-kv` or YaRN is involved. It works: `/props` reports
`total_slots = 3` and it serves.

| requested | v1 (`--parallel 1`) | np 3 | delta |
|---|---|---|---|
| 1k | 326 | 296 | **-9.2%** |
| 2k | 335 | 315 | **-6.0%** |
| 4k | 370 | 375 | +1.4% |
| 8k | 372 | 375 | +0.8% |
| 32k | 325 | 328 | +0.9% |

Cost is concentrated at short contexts and vanishes by 4k, which is consistent with a larger
KV pool costing more to touch per token when there is little context to amortise it over.

The reason to **not** recommend it is memory, not throughput. Available memory went from
37 GiB (np 1) to 27 GiB idle and **19 GiB during the prefill ladder** - the two extra slots
cost ~10 GiB of APU pool, well above the ~6.4 GiB the KV alone would predict. That matters
because this same sweep shows how sharp the cliff is: `-ub 8192` reached 3 GiB available and
lost 63% of prefill. Trading a third of the remaining headroom for concurrency that a
`--parallel 1` agentic loop may never use is a bad trade against a goal that emphasises a
*stable* experience.

Note the asymmetry with occamy, decided the other way: occamy's np 3 is kept, because it runs
on the R9700's own 32 GiB of VRAM and costs the APU pool only ~1.6 GiB of GTT. flash-next's
np 3 comes out of the shared pool. Same flag, opposite answer, because the memory is not the
same memory.

