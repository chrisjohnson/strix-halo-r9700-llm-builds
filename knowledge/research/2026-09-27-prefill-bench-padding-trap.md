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

## The corrected magnitude: ~3-5%, not 43-61%

With real token counts, and corpus windows sized to land on matching token counts
(single stream, cold+warm, same session, same box state):

| actual tokens | synthetic tok/s | real corpus tok/s | delta |
|---|---|---|---|
| ~5.8k (5,798 vs 5,912) | 404 | 382 | **-5.4%** |
| ~11.7k (11,419 vs 11,933) | 388 | 375 | **-3.4%** |

Cold and warm again agree to within ~1-2% on both text types.

**What this does not settle.** Production runs at 262k tokens, and that is precisely where
the two text types diverge most: at 256k the synthetic generator yields 17,610 distinct
trigrams against 127,235 for real text (a 7.2x gap), while at ~12k tokens the gap is far
smaller. The 256k regime is *unmeasured* — those runs are slow and the box was contended.
The honest statement: the repeated-filler problem is real and is now fixed in the harness,
but **its magnitude at production context lengths is still unknown**, and must be measured
on a freed box with real text. Do not port anything on the strength of the 43-61% figure.

## Cross-check: the context falloff is not a PLE signature at all

dirk (`qwen35`, 65 layers, 16 full-attention, **no PLE/engram table of any kind**) logs its
own in-flight prefill on the R9700: 873 tok/s at 4k falling to 593 tok/s at 43k — a 32%
decline. flash-next's recorded ladder showed 31% over 8k->128k. A model with no n-gram
table degrades at least as steeply, which independently confirms the argument from the
trigram data: the context-dependent prefill falloff is a generic attention/KV-scaling
effect, not evidence of an n-gram-table bottleneck.

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

- The 8k-256k ladder on realistic text, cold and warm, is not yet taken — and that is the
  regime where the two text types diverge most (7.2x distinct trigrams at 256k vs far less
  at 12k). It is the number the on-direct port should be judged against, and it needs a
  freed box. Do not size that port from any figure in this note.
- Whether the context-scaling prefill cost is dominated by the full-attention layers or
  the indexer is untested. `--prefill-contexts` with `-fa`/indexer A/Bs on throwaway
  instances would separate them. dirk's 32% falloff with no PLE table makes the
  attention/indexer side the leading candidate, not the n-gram tables.
