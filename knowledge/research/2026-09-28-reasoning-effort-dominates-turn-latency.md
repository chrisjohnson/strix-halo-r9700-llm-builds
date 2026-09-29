---
id: 2026-09-28-reasoning-effort-dominates-turn-latency
date: 2026-09-28
source: measured on the adopted APU build (...-rocm100-lazy-direct-budget-mmproj-...v1, port 8190) 2026-09-28, one hard multi-step prompt, identical in every case except reasoning_effort
tags: [flash-next, reasoning-effort, thinking, wall-time, agentic, tuning, big-moe]
status: active
---

# Reasoning effort can dominate turn latency — but only in proportion to how much the prompt makes it think

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

---

## Correction after validating it (2026-09-28, same day)

A validation run over eight single-fact tasks, each at the new `medium` default and at an explicit
`xhigh`, changes how this should be read. Results:

| | default (`medium`) | `xhigh` |
|---|---|---|
| correct | **8/8** | **8/8** |
| median wall | 4.87 s | 2.29 s |
| median reasoning | 314 ch | 200 ch |
| disagreements | **none** | |
| failures | none - all 16 `finish_reason: stop`, no empty content | |

**Correctness held exactly, which is the good news. But the speed win did not reproduce - it
inverted.** `medium` was 2.13x *slower* on these tasks, and that number is noise rather than a
finding: on easy prompts the model thinks 82-870 characters at *either* level, i.e. 10-80x less
than the 24,376-character probe, so the two levels are effectively indistinguishable in cost here
and the ratio is spread over a few seconds.

**So the 7.5x was not a property of the setting. It was a property of the prompt.** The original
probe asked for a step-by-step proof and to rule out misreadings - it *demanded* exposition - and
`xhigh` obliged with 24,376 characters. Task 1 in the validation set is the same puzzle worded as
"state the final number", and xhigh spent 573 characters on it. The effort level decides how hard
the model thinks when the prompt invites it to; it does not make an ordinary prompt cheaper.

That reframes the change from "the biggest lever found" to something more modest and still worth
keeping: **no measurable downside** on correctness (8/8 both, no disagreement, no failures) and a
**large upside on exactly the prompts that would otherwise provoke very long thinking** - which, for
an agentic loop doing real work, is not a rare case. It should not be sold as a general 6x.

**What is still unvalidated, and it is the case that matters:** eight easy tasks prove nothing about
hard, long-horizon work. A real check needs prompts that actually provoke long chains at xhigh -
the original probe is the right *kind* of material, and the task set was the wrong kind.

**A measurement hazard found while validating, worth knowing:** this engine has `total_slots: 1`,
and something on the box - very likely this very session, whose context is around 200k tokens and
which re-sends its whole history every turn - was sending **209,511-, 212,504- and 162,217-token
prompts** into that single slot, each occupying it for minutes. A repeat run of the 16 measurements
completed **zero** requests, queued behind one of those prefills. Any wall-time number taken on
this box can be dominated by whoever else is using that slot, and this change's benefit is
precisely a wall-time benefit. Measure it in a quiet window or not at all.

## And the test that actually settles it (hard prompts, same day)

The correction above said the missing validation was prompts that *provoke* long chains. Six hard
problems - Monty Hall, Josephus with 100 people, 3^200 mod 7, lattice paths on a 4x4 grid, dice
probability, and a linear recurrence - each with "derive from first principles, then state two
plausible wrong answers and why they are wrong" appended. Correct answers were derived
independently in Python first rather than taken on trust.

| | default (`medium`) | `xhigh` |
|---|---|---|
| correct | **6/6** | **6/6** |
| median reasoning | 3,657 ch | **15,767 ch (4.31x)** |
| median wall (unreliable) | 56.4 s | 145.8 s (2.59x) |
| disagreements | **none** | |
| failures | none - all 12 `finish_reason=stop`, no empty content | |

**`xhigh` thought 4.31x harder and got exactly the same answers right.** That confirms the mechanism
this change rests on - the effort level really does govern how hard the model thinks when the
prompt invites it - and on this sample the extra thinking bought nothing.

So the honest final position: **`medium` is a good default, with no degradation visible at n=6.**
Six problems cannot detect a small cost - if `medium` failed on 1 hard problem in 20, roughly 60
would be needed to see it at 95% confidence - so this is reassurance, not proof. The change is
worth keeping on the evidence available: it is neutral on ordinary prompts, 4.3x less thinking and
2.6x less wall on demanding ones, and no observed correctness cost anywhere.

The wall figures remain the least trustworthy number here for the reason already recorded: a
single slot and a ~200k-token client on it.
