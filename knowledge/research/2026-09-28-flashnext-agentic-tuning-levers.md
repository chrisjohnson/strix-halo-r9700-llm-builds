---
id: 2026-09-28-flashnext-agentic-tuning-levers
date: 2026-09-28
source: measured memory picture of the adopted pair (2026-09-28) plus the §2 agentic findings and the engine comparison; builds referenced are ...-rocm100-lazy-direct-budget-...v1 (APU, role big-moe) and occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2 (R9700, role medium-moe)
tags: [flash-next, occamy, tuning, gtt, kv-cache, prompt-cache, agentic, strix-halo, pair]
status: active
---

# Remaining tuning levers for the flash-next + occamy pair

Chris asked whether the spare GTT is usable. **It is not the constraint, and the real levers are
inside the engine's own allocation choices.** The single most useful finding is that the two
halves of the pair are configured very differently, and the *APU* half is the one behind.

## The measured memory picture (2026-09-28, both halves running)

```
host RAM     124 GiB total, 115 used, 9 available, 12 buff/cache
card0 R9700  vram 31.9 total / 29.0 used      gtt  124.0 total /  1.7 used
card1 APU    vram  1.0 total /  0.2 used      gtt  124.0 total / 84.6 used
```

**GTT is not the limit.** The APU's GTT ceiling is the whole unified pool (124 GiB) and 84.6 GiB
is in use, so ~39 GiB of *GTT* is nominally free — but that number is misleading, because GTT is
just a mapping of host RAM. The binding constraint is **physical RAM: 9 GiB available, plus ~12
GiB reclaimable page cache**, i.e. roughly 20 GiB of genuine headroom. There is no GTT or
`ttm.pages_limit` knob worth touching; raising a GTT limit that already covers all of RAM would
change nothing. What the ~39 GiB figure really says is that **the APU weights are resident in
host RAM and there is not much room left** — which is why the levers below are about spending the
existing budget differently, not about enlarging it.

**The R9700 half is nearly free.** occamy runs in its own 32 GiB of GDDR6 (29.0 used) and touches
1.7 GiB of GTT. So it does not compete with the APU for host RAM, and **the APU can be tuned as if
it owns the box.** That is the main "decide for the pair together" consequence: the pair is
memory-independent, so the APU's budget is ~124 GiB minus a small occamy host footprint, and
nothing done to the APU can starve occamy.

## The asymmetry: occamy is already tuned, the APU is not

| | occamy (R9700, `medium-moe`) | flash-next (APU, `big-moe`) |
|---|---|---|
| KV quant | **`q4_0`** | `f16` |
| prompt cache | **`--cache-ram 32768`** | *unset* — llama.cpp default 8192 MiB |
| parallel | `-np 3` | `--parallel 1` |

Both of occamy's advantages were *measured* here: `q4_0` KV was worth **+73.7% prefill at 8k and
+51.9% at 32k** against `q8_0`, and a larger prompt cache raises the cache-hit fraction, which §2
of PLAN.md identifies as the **dominant term in agentic turn latency** (a production server's own
cache-mode spread is 44x).

So the APU build is running the *documented* pwilkin config, which is a prefill-optimised
measurement configuration, not an agentic one. That is the gap to close.

## Levers, ranked by expected value over cost

**1. `--cache-ram 32768` on the APU build — highest value, near-zero risk.** Unset today, so it is
at llama.cpp's 8192 MiB default while occamy has 32 GiB. §2 says cache-hit fraction is the term
that dominates an agentic turn, and measured hit rate on the APU was **82.1%** with the small
default. With several dsh conversations and subagents in flight, a bigger RAM cache should hold
more prefixes and raise it. Costs RAM (up to ~24 GiB more) — which is exactly what the 9 GiB
available + 12 GiB reclaimable cache is for, and if it does not fit, `--cache-ram` degrades
gracefully rather than failing.

**2. `-ctk q8_0 -ctv q8_0`, then `q4_0`, on the APU build.** Two effects, both wanted: it frees
**3.2 GiB (q8_0) to 4.7 GiB (q4_0)** of the 6.3 GiB f16 KV, and smaller KV means less memory
traffic per token. The occamy result above says the traffic effect can be large. The risk is
**quality**, which is why it must be measured and not just adopted: f16 is what pwilkin's own
documented config specifies, and their writeup is careful about numerics.

**3. `--parallel 2` plus `--kv-unified` — the subagent lever.** `-c 262144` is the total context
split across slots, so `--parallel 2` alone would halve the per-request context. `--kv-unified`
is what makes 2 concurrent full-length slots possible on one pool — the same shared-pool idea
Halogen uses (`HALOGEN_KV_POOL_POSITIONS` vs `HALOGEN_KV_SLOTS`). dsh subagents are what make this
real rather than hypothetical. Needs memory for the second slot's state.

**4. `-b 24576 -ub 24576` — marginal, from their own numbers.** pwilkin's writeup measured
1204.31 tok/s at 16384 against 1199.63 at 24576 back to back, i.e. about 1% *ahead* at depth
40000. Also the largest compute buffer of the four levers. Do it last, if at all.

**Not levers, and worth recording as such:**

- **Context is maxed.** `-c 262144` is the model's full native context and the engine's docs say
  YaRN extension is unsupported. Nothing to gain.
- **A bigger quant is off the table on RAM.** UD-Q4_K_XL is 111.3 GiB against a 124 GiB pool that
  already holds a working model; there is no room for the higher-quality target on the APU.
- **Resident PLE table is a proven loss.** Measured directly: `--tensor-read-lazy off` cost −66%
  at 1k, so keeping the 28.8 GiB table out of the resident set is correct.
- **`--swa-full`, `--context-shift`, `--defrag-thold`** are supported by the engine but nothing
  measured here motivates them; they are not free and would need their own A/B.

## How these should be tested, and what is blocking that

The measurements that would settle levers 1–3 need the APU, and **the APU now serves `big-moe`,
which is dsh's default model** — so any A/B briefly stops the model this session may itself be
running on. That is a deliberate adoption consequence, not an oversight, and it means these need
a short maintenance window rather than being run in the background as the earlier sweeps were.

The right shape once there is a window: one variant per lever, each measured with
`llm-inference-bench/agentic_replay.py` (the §2 metric, where levers 1 and 3 should show) **and**
the prefill ladder (`scripts/pp_tg_at_context.sh`, where lever 2 should show), then adopted only
on a win. Levers are independent enough to test singly, which also keeps the attribution clean —
the engine comparison already showed how much a confounded result can mislead.
