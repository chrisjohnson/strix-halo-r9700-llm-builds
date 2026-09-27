---
id: 2026-09-27-prefill-bench-padding-trap
date: 2026-09-27
source: direct measurement on local-ai-machine — llm_decode_bench.py padding-generator and tokenizer-basis audit, live prefill runs against the running qwen3.8-flash-next build, and dirk's own in-flight prefill log on the R9700
tags: [benchmark, llm-inference-bench, prefill, padding, trigram, ple, engram, tokenizer, qwen3.8-flash-next, methodology]
status: active
---

# The prefill benchmark was measuring repeated filler, not real context

## Finding

`llm_decode_bench.py`'s prefill phase built its test context by cycling a fixed list of
20 sentences: `PADDING_SENTENCES[idx % len(PADDING_SENTENCES)]`. Measured directly, that
text contains **327 distinct trigrams at every context length** — because the text is
literally periodic with period 20 sentences:

| context | total trigrams | distinct trigrams | distinct |
|---|---|---|---|
| 8k | 4,561 | **327** | 7.2% |
| 128k | 74,101 | **327** | 0.4% |
| 256k | 148,460 | **327** | 0.2% |

The distinct count is flat because the generator is periodic. Scaling the context 32x
from 8k to 256k adds 144k trigram *lookups* and **zero** new distinct trigrams.

This matters specifically for qwen3.8-flash-next, whose GGUF metadata describes a PLE
(per-layer embedding) table of 16 heads x ~20M rows x 160 elements — the ~26.8 GiB table
in `qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v1`'s compose comments,
keyed on 3-grams (`qwen4exp.ple.ngram_size = 3`, `ple.heads_per_ngram = 8`). A
327-trigram context touches ~327 x 8 = ~2.6k rows ≈ a couple hundred KB. That working set
is cache-resident no matter how long the context is, so **a benchmark built on this text
cannot measure PLE row-fetch cost at all.** This is the trap called out on llama.cpp PR
#29030 — *"any benchmark built from repeated filler will show this PR doing nothing."*

## Consequence: the recorded 611 -> 420 tok/s ladder does not mean what it was read as

This build's `benchmarks/llm-inference-bench/` results (three runs, 2026-08-30) record:

| context | 8k | 16k | 32k | 64k | 128k |
|---|---|---|---|---|---|
| tok/s | 608-611 | 596-598 | 557-558 | 496-497 | 420 |

All three were on the periodic text above. Since the distinct-trigram count — and
therefore the PLE working set — was **constant at 327** across that whole ladder, the
31% decline from 8k to 128k cannot be attributed to n-gram/PLE table row fetches growing
with context. A fixed working set produces a fixed cost, not a rising one.

So the previously-offered causal story ("mmap sends the 27 GB n-gram table to SSD during
prefill, and that is why prefill falls off with context") is **not supported by the data
that was used to argue it.** The context-scaling cost must live somewhere that actually
scales with context — the 12 of 48 layers that are full attention, and/or the DSA-style
indexer (`attention.indexer.top_k = 2048` selecting over a growing key set). This note
does not claim to have identified that cost; it claims the old ladder does not identify
it either, and that re-measuring on realistic text is a prerequisite to attributing it.

## The tokenizer basis bug — and why the first estimate here was wrong

A first attempt to size the effect compared synthetic with real-corpus text at the same
*requested* context and reported a 43-61% penalty. **That was mostly an artifact of the
harness, and the correction is recorded rather than quietly dropped.**

`tok_per_sec` was `requested_ctx / prefill_time`, and `requested_ctx` is a *character*
budget (`ctx * CHARS_PER_TOKEN`, `CHARS_PER_TOKEN = 4`) — not a token count. Asked to
tokenize the real texts, the live server reported:

| requested ctx | text | chars | **actual tokens** | actual chars/token |
|---|---|---|---|---|
| 8192 | synthetic | 32,768 | 5,608 | 5.84 |
| 8192 | real corpus | 32,768 | 9,211 | 3.56 |
| 16384 | synthetic | 65,536 | 11,230 | 5.84 |
| 16384 | real corpus | 65,536 | 25,079 | **2.61** |

A "16384-token" request was 11,230 tokens of one text and 25,079 of the other — 2.2x
apart. Dividing by the requested number made the two incomparable and inflated every
rate, including the historical ones: the recorded ladder's "608 tok/s at 8k" is really
~430 tok/s over 5,798 real tokens.

Fixed by reading the server's own `timings` block (`prompt_n`, `prompt_ms`,
`prompt_per_second`) from a non-streaming request with `cache_prompt: false`. Without that
flag a repeat of the same prefix scores as a near-zero-token prefill at a meaningless
rate. Results now carry `prompt_tokens` and a `tok_basis` field — `server`, or
`requested-ctx` for engines that report no timings and so fall back to the old,
wrong-by-up-to-2x path.

## The corrected picture: context length costs 23-26%, text diversity costs nothing

All points below are authoritative (server `timings`, `cache_prompt: false`, real token
counts), single stream, one session, one box state, cold+warm:

| text | actual tokens | tok/s |
|---|---|---|
| synthetic | 5,798 | 404 |
| real corpus | 5,912 | 382 |
| synthetic | 11,419 | 388 |
| real corpus | 11,933 | 375 |
| real corpus | 35,300 | 330 |
| synthetic | 45,045 | 297 |
| real corpus | 47,458 | 307 |

Matched-token pairs:

| ~tokens | synthetic | real corpus | real vs synthetic |
|---|---|---|---|
| 5.85k | 404 | 382 | **-5.4%** |
| 11.7k | 388 | 375 | **-3.4%** |
| 46k | 297 | 307 | **+3.4%** |

So text diversity is within noise (about +/-5%) across an 8x span of token counts, and at
~46k tokens the real text carries roughly 3x more distinct trigrams than the synthetic yet
is, if anything, slightly *faster*. Cold and warm agree to within 1-2% at every point.

Context length, by contrast, is large and consistent — **and the falloff is measured
entirely on periodic text**, where the n-gram working set never grows:

| | 5,798 tok | 11,419 tok | 45,045 tok |
|---|---|---|---|
| synthetic tok/s | 404 | 388 | 297 |
| vs 5.8k | — | -4% | **-26.5%** |

This is the finding that should redirect the work. A **26% prefill falloff occurs with the
n-gram/PLE working set held constant at a few thousand rows** — text-driven row fetching
cannot produce that — while enlarging that working set ~3x at the same token count produces
no measurable cost at all. The context-scaling cost is structural: the 12 full-attention
layers and/or the DSA indexer (`attention.indexer.top_k = 2048`, selecting over a growing
key set). It is not the lazy/mmapped n-gram table. dirk's independent 32% falloff with no
PLE table of any kind points the same way.

## Consequence for the planned PR #29030 port

The inherited plan had porting `--lazy-mode on-direct` (parallel `pread` for the n-gram
rows) as its centrepiece, on the strength of a "+20-32% cold prefill" figure. On the
evidence above that port is aimed at a component which is **not the bottleneck in the
measured regime (5.8k-47k tokens)**.

It may still pay at 256k, where the PLE working set is several times larger and is
untested — that measurement has not been taken, and taking it is the prerequisite. But it
should not be built on the assumption that it is the main lever, and the rebase should not
start before that number exists. The 2.5x figure circulating for the change is a DGX Spark
with a table roughly twice this build's size; it is evidence that a real effect exists on
real text, not a prediction for this box.

What the data points at instead is the attention path: whatever scales with context in the
12 full-attention layers and the indexer. That is where a lever would have to live to move
the 26%.

## Cross-check: the context falloff is not a PLE signature at all
dirk (`qwen35`, 65 layers, 16 full-attention, **no PLE/engram table of any kind**) logs its
own in-flight prefill on the R9700: 873 tok/s at 4k falling to 593 tok/s at 43k — a 32%
decline. flash-next's recorded ladder showed 31% over 8k->128k. A model with no n-gram
table degrades at least as steeply, which independently confirms the argument from the
trigram data: the context-dependent prefill falloff is a generic attention/KV-scaling
effect, not evidence of an n-gram-table bottleneck.

## The external number for the lazy-read fix is much larger than the one this work cited

The session that started this work cited PR #29030 as *"+20-32% cold prefill on Strix
Halo"*. The primary discussion is more pointed, and it is explicitly a **real-text**
number: for this model, `--lazy-mode on-direct` reads the 16 rows per token with `pread`
instead of mmap, and *"on a Spark it took real-text prefill from about 300 to 750 tok/s"* —
roughly **2.5x**, on a DGX Spark, with the table stored Q8_0 at 50.66 GiB
([forums.developer.nvidia.com](https://forums.developer.nvidia.com/t/theoretical-feasibility-of-running-qwen-3-8-flash-next-q5-quant-vision-enabled-80k-context-on-dgx-spark/382088)).

Two things follow. First, the size of the win depends enormously on the baseline text, which
is the entire point of this note — a repeated-filler baseline is the one measurement that
cannot see it. Second, the 2.5x figure is a *different machine with a table roughly twice
the size* (50.66 GiB Q8_0 vs this build's 26.8 GiB IQ4-class), so it does not transfer as a
predicted gain here; it is a strong indication that a real effect exists and is measurable,
not a number to plan against.

The same thread's operating advice is worth keeping: leave the table lazy (do not set
`--lazy-mode off`, which makes all 50.66 GiB resident, and do not force it to a GPU with
`-ot` — that is issue #28201), keep `--cache-ram 0` and `-np 1`, and on that platform *"no
userland limit makes a run fail cleanly"* — so stage context sizes up rather than jumping
straight to 256k.

## Also found: the bench misdetects a llama.cpp server as SGLang

Every recorded flash-next result carries `"engine": "sglang"` — but the target is
`llama-server`. `_detect_engine()` falls through to *"Could not detect engine. Assuming
SGLang."* The consequence is silent, not loud: every server-side metric in those results
is `0.0` (`server_gen_throughput`, `server_utilization`, `server_spec_accept_rate`),
because the SGLang `/metrics` scrape matched nothing. The prefill numbers remain valid
(they are TTFT-derived, client-side), but nothing in those files that claims to describe
server behaviour actually does. Not fixed here — recorded so it is not mistaken for a
measurement.

## What changed (2026-09-27)

`llm_decode_bench.py`:

- `generate_padding_text()` is now combinatorial (templates x slot vocabularies) and
  seeded, not periodic: **17,610 distinct trigrams at 256k, 54x the old figure.**
- `--padding-seed` makes that text byte-identical across runs, so two builds can be A/B'd
  on identical input. Previously every run got a random `run_id` prefix and the same
  periodic body.
- `--context-file` uses a real corpus instead. This is the authoritative mode: the same
  audit shows synthetic prose still plateaus well below real text —
  **127,235 distinct trigrams at 256k (89.3% distinct) from 2.8 MB of this repo's own
  source and docs, vs 17,610 (11.9%) synthetic.** A fixed vocabulary cannot reach real
  text's trigram space at any seed.
- Each context length now gets its own body rather than a truncated copy of one shared
  base. The shared base made every longer context inherit pages an earlier, shorter
  context had already faulted in — i.e. it measured a partly **warm** cache for exactly
  the cold cost under test. The prefill warmup likewise now uses a different body at the
  same token count, so the smallest context's first-touch sample is not pre-warmed.
- Prefill records and prints **first-touch (cold)** and **repeat (warm)** separately.
  The lazy-read / `on-direct` change this work is evaluating is specifically a cold win
  that is near-flat cold-to-warm, so a single blended number hides it either way.
  Previously `repeats` was `1` for every context >= 8k: a cold number with nothing to
  compare it against. `tok_per_sec` is retained as the blended headline so existing
  result files and dashboards keep working.
- Prefill rates now come from the server's own `timings` (`measure_prefill_server()`),
  with `cache_prompt: false` so the prompt is genuinely reprocessed. This removed the
  `CHARS_PER_TOKEN` assumption described above. TTFT remains the fallback for engines
  that report no timings, and `tok_basis` records which path produced a number.

## Open questions

- **256k is still unmeasured.** Everything here is 5.8k-47k tokens. The PLE working set is
  several times larger at 256k and the falloff may change character there, so the on-direct
  port is neither endorsed nor ruled out by this note — it is un-prioritised until that
  number exists. It needs a freed box (dirk contending for memory bandwidth is a real
  confound on absolute values, though not on the matched synthetic-vs-real comparisons,
  which were taken back to back).
- **What in the attention path costs the 26%?** The leading candidates are the 12
  full-attention layers and the DSA indexer's top-2048 selection over a growing key set.
  Separating them is cheap on a freed box: `--prefill-contexts` at matched token counts with
  the indexer's sparse selection disabled (if the build exposes it), and `-fa on/off`.
  This is now the highest-value measurement, ahead of the port.
- Whether the 256k KV/cache geometry (see the companion memory-budget note) changes the
  prefill picture once occamy moves to the R9700 and the APU's page cache has more room.
