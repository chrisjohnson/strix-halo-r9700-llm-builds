---
id: 2026-09-27-no-29030-port-attention-path-instead
date: 2026-09-27
source: measurement work on local-ai-machine, 2026-09-27 — see knowledge/research/2026-09-27-prefill-bench-padding-trap.md for the full data; originated from an opencode session (ses_f1e8a695effexdiSmnjJjCAKhc) whose plan had this port as its centrepiece
tags: [qwen3.8-flash-next, prefill, performance, llama.cpp, lazy-mode, mmap, ple, ngram, pr-29030, scope]
status: active
---

# Do not port llama.cpp PR #29030's `--lazy-mode on-direct`; investigate the attention path instead

**Decision**: drop the EngramHalo-fork rebase onto PR #29030 (`--lazy-mode on-direct`,
parallel `pread` for the n-gram/PLE rows) from the flash-next tuning plan, and spend the
effort on the attention path — the 12 full-attention layers and the DSA indexer — instead.

**Authority**: this is an engineering recommendation standing on measurement, not a decision
Chris made. It reverses the ordering in the plan he was shown, so it is recorded explicitly
here and flagged to him rather than applied silently. He can override it; the reversal
condition is in the last section.

**Why**: the port targets the lazy/mmapped n-gram table. Three independent lines of
measurement on this box say that is not where the prefill time goes.

1. **The falloff happens with the n-gram working set held constant.** On *periodic* text —
   where the distinct-trigram count never grows — prefill falls 65%, from 404 tok/s at 5.8k
   tokens to 141.8 tok/s at 250,867 tokens. A fixed working set cannot produce a
   context-dependent cost. The whole 250k curve is in the research note.

2. **Realistic text is *faster*, not slower.** Compared by the same instrumentation (the
   server's own prompt-processing log) and matched on actual tokens:

   | tokens | synthetic | real corpus | real vs synthetic |
   |---|---|---|---|
   | 32,768 | 360.5 | 363.5 | +0.8% |
   | 65,536 | 277.7 | 300.5 | +8.2% |
   | 98,304 | 231.6 | 260.4 | +12.5% |
   | 114,688 | 215.1 | 246.0 | +14.3% |

   The real-corpus run carried 34,519 distinct trigrams at 119,040 tokens, roughly 3x the
   synthetic's coverage. If gathering 3x more distinct rows from the 26.8 GiB PLE table
   cost anything, it would appear as a penalty on the real text. It appears as the
   opposite, and the advantage *grows* with context.

3. **A model with no PLE table behaves the same way.** dirk (`qwen35`, no n-gram/engram
   table of any kind) logs its own in-flight prefill on the R9700 falling 873 -> 593 tok/s
   (32%) from 4k to 43k.

The PLE table is a real ~26.8 GiB structure and the lazy-read path is real, but on this box
it is not the lever. The `on-direct` gain circulating for the change (~300 -> ~750 tok/s) is
a DGX Spark with a table roughly twice this build's size; on this box the one comparable
real-text measurement comes out in the opposite direction.

**Alternatives considered**: (a) *Port as originally planned* — rejected: it is a fork
rebase with known conflict sites (`load_arch_tensors()`, the `ple_w` scope break, the local
`llama-cpp-qwen38-per-buffer-mmap.patch`) against evidence that the component it fixes is
not the bottleneck. (b) *Config-only A/Bs first, then decide* — this is what is happening;
the port is deferred, not banned. (c) *Nothing* — rejected: the 65% falloff is real and
worth attacking, just not there.

**What would reverse this**: the matched comparison above is only taken to ~115k tokens, and
neither text type has been run to a full 251k on the same footing. If a full-context
real-text run shows the PLE path opening up — i.e. real text becomes materially *slower*
than periodic text at 251k, inverting the trend above — the port goes back on the table.
Requires docker access to run the sweep; see the local-ai-machine commit `a1fe57b` that
grants it.

**Source**: the measurements are in `knowledge/research/2026-09-27-prefill-bench-padding-trap.md`
(the full curve, the matched comparisons, and the two harness bugs — a repeated-filler
generator and a prefill rate computed against the *requested* context rather than the real
token count — that had to be fixed before any of it was trustworthy). The port itself came
from the opencode session named in the frontmatter, which inherited it from an external
chatbot's advice.
