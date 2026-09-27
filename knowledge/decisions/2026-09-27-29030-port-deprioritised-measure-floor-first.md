---
id: 2026-09-27-29030-port-deprioritised-measure-floor-first
date: 2026-09-27
source: measurement work on local-ai-machine, 2026-09-27 — knowledge/research/2026-09-27-flashnext-prefill-constant-floor.md and 2026-09-27-prefill-bench-padding-trap.md; supersedes 2026-09-27-no-29030-port-attention-path-instead.md, which was written from partial data and over-claimed
tags: [qwen3.8-flash-next, prefill, performance, llama.cpp, lazy-mode, mmap, ple, ngram, pr-29030, scope, superseded-earlier-revision]
status: active
---

# Deprioritise the PR #29030 port for the falloff — but measure the 2.58 ms/token constant floor before dropping it

**Decision**: the EngramHalo-fork rebase onto PR #29030 (`--lazy-mode on-direct`, parallel
`pread` for the n-gram/PLE rows) does **not** address the context-length prefill falloff, and
should not be justified by it. It is **not** dropped. Before deciding whether to build it,
measure how much of the constant 2.58 ms/token prefill floor the PLE gather accounts for —
which is cheap and needs docker access.

**Authority**: an engineering recommendation standing on measurement, not a decision Chris
made; recorded here rather than applied silently. Reversal condition at the end.

**Revision note**: this supersedes an entry written earlier the same day
(`2026-09-27-no-29030-port-attention-path-instead`), which concluded "do not start the
rebase". That was over-claimed. The measurements it rested on are sound and are restated
below; what was missing was the distinction between *"the PLE path does not cause the
falloff"* and *"the PLE path costs nothing"*. The constant-floor measurement taken
afterwards shows the second claim does not follow from the first, so the earlier entry has
been removed rather than quietly edited.

**Why the port is not the cause of the falloff** — three independent lines:

1. Prefill falls 65% (404 -> 141.8 tok/s) from 5.8k to 250,867 tokens **on periodic text,
   where the n-gram working set never grows**. A fixed working set cannot produce a
   context-dependent cost.
2. At matched token counts, real text — carrying ~3x more distinct trigrams — is **faster**
   than that periodic text, by 0.8% at 32.8k rising to 14.3% at 114.7k (same instrumentation,
   the server's own prompt-processing log).
3. dirk (`qwen35`, no PLE/engram table at all) shows a 32% falloff of its own, 873 -> 593
   tok/s from 4k to 43k.

**Why that does not dismiss the port**: the gather is **16 rows per token** (fixed per token,
not per distinct n-gram — which is *why* point 2 is true), the PLE tensor is mmap-backed on
CPU with whole-file prefetch deliberately disabled by this build's own patch, and its rows
are demand-faulted. So it is a *constant* per-token cost, and there is a large constant
per-token cost to attack: fitting prefill at 1.4k-9.4k tokens gives
`ms/token = 2.576 + 562/tokens`, i.e. a floor of **~2.58 ms/token that is ~37% of the
per-token cost at 250k and ~87% at 1.4k**. 16 rows inside 2.58 ms would be ~161 us per row if
serialised — plausible for cold random reads, but unproven: the floor also contains the 36
SSM layers' state updates, MoE routing, the context-independent share of the 12
full-attention layers, and KV writes, and compute alone should be well under 1 ms/token.

**What settles it** (all cheap, all need a throwaway instance, all at 1k-8k tokens where a
run takes seconds): `--tensor-read-lazy off` / `--lazy-mode off` to make the table resident
and see whether the floor collapses; `--load-mode dio` to separate bulk-weight I/O from the
table's mmap path; and a repeat of the 1k/2k/4k/8k ladder for error bars.

**Alternatives considered**: (a) *Port as the inherited plan had it* — rejected as the
answer to the falloff, not as an idea. (b) *Drop it entirely* — rejected; that was the
earlier, over-claimed position. (c) *Config-only A/Bs first* — this is what happens next; the
two measurements above are exactly that, and the remaining ones need docker access.

**What would reverse this**: a floor measurement showing the PLE gather is a small share of
2.58 ms/token would drop the port for good. A measurement showing it is most of the floor
would make it the single highest-value change available, since it would apply at every
context length rather than only at long ones.

**Source**: the falloff curves, the matched text comparison and the two harness bugs that had
to be fixed first are in `knowledge/research/2026-09-27-prefill-bench-padding-trap.md`. The
constant-floor fit, its caveats, and the flag-level plan to decompose it are in
`knowledge/research/2026-09-27-flashnext-prefill-constant-floor.md`. The port itself came
from the opencode session named in the padding-trap note, which inherited it from an external
chatbot's advice.
