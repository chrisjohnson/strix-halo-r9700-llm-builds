---
id: 2026-09-27-flashnext-decode-vs-context
date: 2026-09-27
source: direct measurement on local-ai-machine against the running qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v1 build, via llm_decode_bench.py --skip-prefill
tags: [qwen3.8-flash-next, decode, throughput, context-length, attention, indexer, strix-halo, benchmark]
status: active
---

# Decode also falls off with context: 18.0 -> 11.7 tok/s by 64k

## Finding

Single stream, MTP speculative decoding on, real-corpus prompts (2.8 MB of this repo's own
source and docs), 20-second measurement cells after a warmed prefill:

| context | decode tok/s | vs empty context | TTFT |
|---|---|---|---|
| 0 | 18.0 | — | 0.70s |
| 16,384 | 16.5 | -8.3% | 0.20s |
| 32,768 | 12.5 | -30.6% | 0.23s |
| 65,536 | **11.7** | **-35.0%** | 0.45s |

The TTFT column is the check that these are decode numbers and not prefill leaking in: at
0.2-0.7s the prompt was already resident (the harness warms the radix cache for each context
before measuring), so the measurement is pure decode over a KV cache of that size.

## Why this matters alongside the prefill result

Prefill and decode are usually discussed as if one of them is the bottleneck. On this build
**both fall off sharply with context**, and they are separate problems. The two series below
come from different instruments, so each row is labelled with its own basis and the rows
should not be subtracted from each other:

| axis | small context | 64k | 251k |
|---|---|---|---|
| prefill tok/s (server-log basis, synthetic text) | 360.5 @ 32.8k | **277.7** | **141.8** |
| decode tok/s (harness cells, real corpus) | 18.0 @ 0 | **11.7** | not measured |

Within its own series that is a **-61%** prefill falloff from 32.8k to 251k and a **-35%**
decode falloff from 0 to 64k.

So a full-context turn on this build is roughly a ~30-minute prefill followed by generation
at a rate that has already lost a third of its speed by 64k and is not measured beyond that.
The `--skip-prefill` decode numbers are the cheap half of this picture; the 256k decode point
is the missing one.

## Most likely shared cause

The same one the prefill note points at: the 12 of 48 layers that are full attention, plus
the DSA indexer (top-2048 selection over a growing key set). Decode attends over the whole
KV every token, so a growing KV is a direct cost here in a way that is easier to attribute
than in prefill. The 36 linear-attention (SSM) layers have a fixed-size recurrent state and
should be roughly context-independent — so if decode is down 35% by 64k, that is the
full-attention/indexer share growing.

Note the shape: only -8% by 16k, then -31% by 32k. A step rather than a smooth curve, which
is worth re-measuring before reading much into — it may be a threshold effect in the indexer
or simply cell-to-cell noise at n=1 per point.

## Caveats

- One 20-second cell per context, single run. No error bars; the 16k -> 32k step is the one
  worth re-taking with repeats.
- With MTP enabled, tok/s mixes raw decode speed with draft acceptance, which is content
  dependent. This build's own notes record acceptance of 100% short / 84.5% medium /
  88.5-81.25% multi-turn and long-context, so acceptance does not obviously improve with
  context here — but it is not held constant across these cells either.
- 64k is the largest context measured. Production runs at 262k, so the extrapolated
  full-context decode rate is unknown and should not be quoted as a number.
- Measured with dirk resident on the R9700. That is a small confound for APU-side decode
  (dirk holds its weights in its own VRAM and ~4.8 MB of host RSS) but not zero.

## Method

```
llm_decode_bench.py --host 127.0.0.1 --port 8152 \
  --skip-prefill --contexts 0,16384,32768,65536 --concurrency 1 \
  --duration 20 --max-tokens 1024 \
  --context-file <2.8MB corpus> --padding-seed bench
```

Harness state at the time of measurement: commit `cbde1af` or later, i.e. with the
`CHARS_PER_TOKEN` rate bug fixed and real token counts recorded. Note that `--skip-prefill`
means the prefill table is empty and the `tok_basis` / `prompt_tokens` fields do not appear
for this run — decode cells do not carry them.

## Addendum: decode has a ~8-11% run-to-run noise floor, and a sampling seed does not remove it

Every decode number in this note is one run. Before trusting any *comparison* between two
configs, the measurement needed error bars, so the harness gained a fixed sampling seed
(`--gen-seed`, default 1234) on the theory that decode variance comes from MTP draft
acceptance, which depends on the generated content, and the model samples at temperature 1.0.

**That theory is only part of it.** Two seeded runs of the *same* build, same cell, same
prompt, same seed:

| run | ctx 0 | ctx 16k | ctx 32k |
|---|---|---|---|
| seeded #1 | 21.9 | 17.3 | 15.2 |
| seeded #2 | 20.3 | 15.9 | 16.9 |
| spread | 7.9% | 8.8% | **11.2%** |

So the seed is still the right thing to send, but it leaves 8-11% of variance that is *not*
sampling content — graph-compilation warmth in the first cell, KV/allocator placement, and
whatever else varies between runs on this box. The practical consequence is worth stating
plainly:

**Decode differences below roughly 10% are not resolvable here** without many repeats, and
every decode figure in this note should be read with that band. In particular, the
`ROCBLAS_USE_HIPBLASLT` question - whether it helps or hurts decode - is **not resolvable**
at practical sample sizes: the observed v1-vs-v2 difference sits inside v1's own spread, so
the honest answer is "no measurable effect" rather than "no regression we happened to find".
The prefill case for that change does not depend on decode: five monotonic points, +4.6% to
+9.5%, measured on server-reported timings that are not subject to this variance.
