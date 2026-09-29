---
id: 2026-09-28-reasoning-effort-dominates-turn-latency
date: 2026-09-28
source: measured on the adopted APU build (...-rocm100-lazy-direct-budget-mmproj-...v1, port 8190) 2026-09-28, one hard multi-step prompt, identical in every case except reasoning_effort
tags: [flash-next, reasoning-effort, thinking, wall-time, agentic, tuning, big-moe]
status: active
---

# Reasoning effort dominates turn latency — 7.5x, measured

Same build, same prompt, same 32768 cap, three effort levels. Only `reasoning_effort` changed:

| effort | wall | reasoning | answer | correct |
|---|---|---|---|---|
| **low** | **43.4 s** | 3,654 ch | 1,343 ch | **yes** |
| **medium** | **34.4 s** | 2,224 ch | 1,887 ch | **yes** |
| default (`xhigh`) | **257.1 s** | 24,376 ch | 722 ch | (not checked) |

**7.5x on wall time, and the shorter-thinking answers came out *longer* and correct** - both low and
medium produced 12 sheep with the right chain (9 remain, +3, sell half, double). The default spent
24,376 characters thinking and then answered in 722.

For scale: the whole engine comparison that produced the adopted build was worth **2.62x prefill
and 2.36x decode**. This single setting is worth more than that, needs no download, no model
change, and is reversible per request.

## Why it is so large: thinking is where the tokens go

From this repo's own probes on the same engine: 26,143 characters of reasoning against 2,750 of
answer at cap 32768; 25,451 against 2,164 at 16384. **Roughly 90% of what the model generates is
thinking.** So turn wall time is thinking-bound, and the prefill/decode work this repo spent days
tuning is the minority of what a user waits for.

That also reframes the Strata finding. Its lead that mattered was "thinks shorter" - Swift 1.5,
described as 63% fewer thinking tokens. **We can buy the same thing with a flag we already
declare**, which is strictly better than buying it by swapping to a foreign fine-tune that exists
only at 2-3 bit and ships no MTP head.

## The mechanism, and why it was not already on

`big-moe` declares `reasoningEfforts: {low, medium, xhigh}` with `compat.supportsReasoningEffort`,
verified live when the role was created. But **omitting it leaves the template's own `xhigh`
default in force** - and nothing sets a default level, so every turn has been running at xhigh.
The levels were available and unused.

## The caveat, stated because it is the whole risk

**One problem is not a quality benchmark.** Both low and medium got this one right, and the
default got it right too (its answer was checked only for being non-empty); what 7.5x does to
success rate on genuinely hard work is unmeasured. The plausible mechanism is real in both
directions: less thinking should cost accuracy on hard tasks, and less thinking also makes it
**less likely to blow the output cap**, which is the failure that returns empty content.

There is also tension with the earlier Halogen reading, which advised *bounding* thinking at xhigh
rather than lowering effort for agentic work. Both are defensible: a budget preserves the model's
reasoning within a ceiling, while lowering effort changes how much it reasons at all. This
measurement is of the latter, and it is the larger effect by far.

## What to do with it

Set a default level on the roles that serve interactive agent loops - `medium` is the natural
starting point, being 44% faster than low here while thinking more - and keep `xhigh` available
for work that warrants it. Then measure success rate on a spread of real tasks before treating it
as settled, because the speedup is large enough to be worth the checking and the failure mode
(worse answers, quietly) is the expensive kind.
