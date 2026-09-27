---
id: 2026-09-27-prefill-bench-padding-trap
date: 2026-09-27
source: direct measurement on local-ai-machine (llm_decode_bench.py padding-generator audit + one live run against the running qwen3.8-flash-next build)
tags: [benchmark, llm-inference-bench, prefill, padding, trigram, ple, engram, qwen3.8-flash-next, methodology]
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

## How much the filler flattered the numbers

A first live run against the running flash-next server with the new generator
(8k/16k only, single stream, cold+warm):

| context | old filler (2026-08-30) | new diverse text (2026-09-27) | delta |
|---|---|---|---|
| 8k | 608-611 | 583 | -4.1% |
| 16k | 596-598 | 562 | -5.9% |

Caveat, stated plainly: these are different days on a box whose other resident models
changed between them, so treat the magnitude as indicative and the *direction* as the
finding. The gap should widen with context, since distinct-trigram count grows with
context under the new generator and was pinned under the old one.

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

## Open questions

- The re-measured 8k-256k ladder on realistic text, cold and warm, is not yet taken. That
  is the number the on-direct port should be judged against.
- Whether the context-scaling prefill cost is dominated by the full-attention layers or
  the indexer is untested. `--prefill-contexts` with `-fa`/indexer A/Bs on throwaway
  instances would separate them.
