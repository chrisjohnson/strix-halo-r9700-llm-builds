---
id: 2026-09-27-flashnext-occamy-256k-memory-budget
date: 2026-09-27
source: direct measurement on local-ai-machine — /proc/meminfo + amdgpu sysfs GTT/VRAM counters, GGUF metadata for all three models, dirk's live VRAM footprint, and dirk's in-flight prefill log
tags: [memory, vram, gtt, r9700, strix-halo, qwen3.8-flash-next, occamy, dirk, kv-cache, topology, planning]
status: active
---

# Does flash-next + occamy both fit at 256k? Yes — the earlier "it doesn't fit" was wrong

## Finding

The tuning session that produced this work concluded that running qwen3.8-flash-next on the
APU **and** occamy on the R9700, both at 256k, was infeasible:

> *"165-173 GiB against 124 GiB. Even at `--cache-ram 0` on occamy it's ~135 GiB. It does
> not fit."*

**That arithmetic is wrong, and the conclusion with it.** It added the R9700's workload to
the APU's 124 GiB unified pool. The R9700 is a discrete PCIe card with its own 32 GiB of
GDDR6, and work it does costs the host pool nothing.

## Evidence the R9700's memory is its own

| observation | value |
|---|---|
| `card0` (R9700) `mem_info_vram_used` | **30.68 GiB** |
| dirk's process `VmRSS` while serving from that VRAM | **4.8 MB** |
| `card0` `mem_info_gtt_used` (host spill) | 0.56 GiB |
| host memory unaccounted for by every meminfo bucket | **76.4 GiB** |
| `card1` (APU) `mem_info_gtt_used` | **77.1 GiB** |

dirk is holding 30.68 GiB of VRAM with a process RSS of 4.8 MB — that memory is on the
card, not in the host pool. And the 76.4 GiB the standard `meminfo` categories
(`AnonPages`/`Cached`/`Shmem`/`Slab`/`Buffers`) cannot account for matches card1's 77.1 GiB
GTT to within 1%. So the APU pool is consumed by the APU's GTT, and the R9700 contributes
essentially nothing to it. (This also answers the "94 GiB used but no process shows it"
question the session died on: amdgpu accounts GTT outside those buckets.)

## The KV formula, validated end-to-end against dirk

Hybrid linear-attention models only pay KV on their full-attention layers
(`full_attention_interval = 4`, so one layer in four):

```
KV bytes/token = n_full_attn_layers x 2(K,V) x head_count_kv x key_length x bytes_per_elem
```

dirk is the control, because its VRAM use is directly observable:

| dirk (`qwen35`) | value |
|---|---|
| block_count / full_attention_interval | 65 / 4 -> **16** full-attn layers |
| head_count_kv, key/value_length | 4, 256/256 |
| KV/token | 16 x 2 x 4 x 256 = **32,768 elem** |
| KV at 262,144, `q4_0` (0.5625 B/elem) | **4.50 GiB** |
| weights file | 23.56 GiB |
| **predicted** weights + KV | **28.06 GiB** |
| **observed** `card0` VRAM | **30.68 GiB** |
| residual (vision mmproj F16 + graphs/buffers) | ~2.6 GiB — plausible |

q4_0 = 32 weights/block in 2 (fp16 scale) + 16 bytes = 0.5625 B/elem; q8_0 = 2 + 32 = 1.0625.
The prediction lands within 9% of observed with the residual fully explained by the vision
projector dirk loads (`--mmproj ... F16`) plus compute buffers, so the formula is trusted
for sizing.

## occamy on the R9700 at 256k

| occamy (`qwen3_5_moe_text`) | value |
|---|---|
| block_count / full_attention_interval | 40 / 4 -> **10** full-attn layers |
| head_count_kv, head_dim | 2, 256 |
| KV/token | 10 x 2 x 2 x 256 = **10,240 elem** |
| KV per 256k slot, `q8_0` | **2.66 GiB** |
| KV per 256k slot, `q4_0` | **1.41 GiB** |
| weights (Q4_K_M, MTP grafted in) | **20.22 GiB** |
| vision mmproj F16 | 0.84 GiB |

Against 31.86 GiB of usable VRAM:

| config | weights | KV | mmproj + buffers | total | headroom |
|---|---|---|---|---|---|
| `-np 1`, q8_0 | 20.22 | 2.66 | ~2.3 | **~25.2** | 6.6 GiB |
| `-np 3`, `q8_0` (current flag set) | 20.22 | 7.99 | ~2.8 | **~31.0** | **0.9 GiB — too tight** |
| `-np 3`, `q4_0` | 20.22 | 4.23 | ~2.8 | **~27.3** | 4.5 GiB |

So occamy at 256k does fit on the R9700, but **its current `-np 3` + `q8_0` combination
leaves under a gigabyte of margin**, and it must not also reserve host `--cache-ram` if the
APU's page cache is to be protected. `q4_0` KV is the obvious lever: dirk already runs
`-ctk q4_0 -ctv q4_0` on this same card without incident, and it turns 0.9 GiB of margin
into 4.5 GiB for ~3.8 GiB of host-side pressure relief.

## flash-next on the APU at 256k

| flash-next (`qwen4exp`) | value |
|---|---|
| block_count / full_attention_interval | 48 / 4 -> **12** full-attn layers |
| head_count_kv, key/value_length | 2, 256/256 |
| KV/token | 12 x 2 x 2 x 256 = **12,288 elem** |
| KV at 262,144, `q8_0` | **3.19 GiB** (not the ~17-18 GiB the session estimated) |
| weights (3 GGUF shards) | **87.25 GiB** |
| MTP head `Q8_0` | 3.85 GiB |
| PLE / n-gram table (in the weights) | ~26.8 GiB |

Weights + MTP + KV is ~94.3 GiB against a 124.4 GiB pool, leaving ~11-13 GiB for page
cache after the ~14 GiB service floor. That is **less than half of the 26.8 GiB PLE
table**, so the PLE table cannot be fully resident alongside occamy — a real fraction of
every prefill stays cold. (Live confirmation: card1's GTT was 77.1 GiB while the model's
resident working set is ~94 GiB, i.e. ~17 GiB is already cold on SSD today.)

## Correction: `--cache-ram` is not why the page cache collapsed

The session attributed the collapse to *"`--cache-ram 32768` on occamy and `24576` on dirk —
56 GiB of explicit host-RAM cache reservations"*. That is not what is happening: dirk runs
with `--cache-ram 24576` and its process RSS is **4.8 MB**. The reservation is not resident.
Whatever is squeezing the APU pool, it is not a preallocated 56 GiB of host cache.

## What this means for the plan

- The target topology is feasible: **flash-next on the APU, occamy on the R9700, both at
  full 256k** — provided occamy's KV is `q4_0` (or `-np 1`) and it keeps host `--cache-ram`
  at zero or small.
- Nothing about occamy's footprint needs to come out of the APU pool, so the two models do
  not actually compete.
- The APU's page-cache shortfall against the 26.8 GiB PLE table is the real residual, and it
  is a *page-cache* problem, not a "models don't fit" problem.
- occamy on the R9700 needs its own build entry (`-dev Vulkan0`, R9700 port range, no
  `--cache-ram`) rather than reusing the strix-apu one — the existing build pins
  `-dev Vulkan1` and `--cache-ram 32768`, both wrong for the R9700.

## Caveats

The KV figures are computed from GGUF metadata with a formula validated on exactly one
model (dirk, within 9%). Compute-buffer sizes are estimated, not measured, which is the
bulk of the uncertainty in the headroom column — the `-np 3`+`q8_0` case is the one where
that matters. The final numbers should be confirmed by actually launching the candidate
occamy build on the R9700 and reading `mem_info_vram_used`.
