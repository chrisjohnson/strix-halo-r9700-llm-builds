---
id: 2026-09-27-halogen-agentic-tuning-lessons
date: 2026-09-27
source: reading peonist-ai/halogen-flash-server's README (139 KB) and docker-compose.yml, 2026-09-27 — a closed-source (NOASSERTION) Qwen3.8-Flash-Next server for gfx1151, 731 stars, the engine whose 1.2k t/s prefill claim motivated pwilkin's work. Homepage https://huggingface.co/peonist-ai/halogen-qwen3.8-flash-next
tags: [agentic, prompt-cache, halogen, tuning, dsh, deepseek-replacement, reasoning-effort, kv-pool]
status: active
---

# What a production Flash-Next server tunes for, and what this repo has been missing

**The reframe.** This repo has been optimising *prefill tok/s*. That is not the metric an
agentic harness experiences. A dsh session is a **long conversation that grows**: every turn
re-sends the whole history, plus tool definitions and tool results, and every so often a
compaction re-reads all of it cold. The number that matters is **end-to-end latency of a turn
in a growing conversation**, and raw prefill is only one of its three terms — and not the
largest one.

Halogen's own measurements make the ranking concrete. Over a 20-turn conversation growing from
90k to 108k tokens, adding ~1,000 tokens a turn:

| its prompt-cache mode | follow-up turn at 100k |
|---|---|
| `2` — save at end of system prompt, start of last message, end of every request (default) | **~2 s** |
| `1` — save only at fixed checkpoints | ~17 s |
| `0` — never save | ~88 s |

**A 44x spread on the same engine, same weights, same hardware.** No kernel change in this
repo's whole history is worth more than a fraction of that. So the first agentic question is
not "how fast is prefill" but **"how much of each turn is a cache hit, and does our stack
resume where the last turn stopped?"**

## What we already know about ours

`2026-09-27-flashnext-incremental-prefill-and-prompt-cache.md` measured exactly this, without
framing it as the headline:

| our case | time |
|---|---|
| cold, 55,460 tokens | 184.76 s |
| grown by ~3.7k tokens, 53,408 served from cache | 15.76 s |
| byte-identical repeat | 0.32 s |

So llama.cpp's prefix cache does work and the effect is the same shape. Normalised,
**~235 tok/s effective on the increment** against Halogen's ~500 — which is roughly the
prefill-rate ratio (we measure 326–434 tok/s at 8k–32k; they claim 1,041 at pp8192). That is
consistent: **our cache architecture is not obviously wrong; our per-token prefill rate is the
weaker term**, which is exactly what the engine work in `2026-09-27-strix-halo-engine-landscape.md`
addresses.

## The reliability findings, which we have not examined at all

These are the parts most likely to be biting us in real dsh sessions, because they fail
*silently or as retries* rather than as slowness:

1. **The "answer room".** Agent harnesses send no thinking control to an OpenAI-compatible
   server unless configured to, so **the server's defaults are what the harness runs at**, and
   the model's own `xhigh` effort runs under whatever cap the harness set for the *answer*.
   Before Halogen 0.11.0, a budget that ran out mid-thought did not shorten the answer — it
   **removed** it: `finish_reason: "length"`, empty `content`, partial reasoning in
   `reasoning_content` that most clients do not display. Their words: *"a compaction summary
   capped at 13,000 tokens that the model thinks past is a compaction that fails, and the
   harness retries it."*
   Their fix reserves `max(1024, 15% of max_tokens)` for the answer, and reports
   `reasoning_closed_by: "answer_room" | "max_thinking_tokens"` so a client can tell.
   **We have not checked whether our flash-next builds do anything equivalent.** If they do not,
   dsh compactions on the local model are failing-and-retrying in a way that looks like slowness.
2. **Thinking can loop at long context.** *"Greedy decoding at 100k+ of context can loop inside
   the block and spend the whole budget there (issue #56: 32,000 tokens of reasoning and an
   empty answer)."* A `max_thinking_tokens` cap bounds the damage when a client sends none.
3. **Effort is a 3-level template, not 5.** `minimal`/`low` → low, `medium` → medium,
   `high`/`xhigh` → xhigh. Declaring five distinct levels in a client would be a lie. This is
   the same trap `local-ai-machine`'s own AGENTS.md warns about for `reasoningEfforts`.
4. **Prompt cache on disk.** `HALOGEN_CACHE_DIR` persists the cache, so a conversation
   **survives a server restart**: a 32k conversation restarted reached first token in a few
   seconds against ~40 s cold. ~27 KiB per token on disk (0.9 GB at 32k, 7.2 GB at 262k).
   **llama.cpp has no equivalent** — its `--cache-ram` is memory-only, so a dsh session resumed
   after a model restart re-prefills its entire history. That is a real, unaddressed agentic
   cost on our stack.

## The concurrency finding, which maps onto our `--parallel` work

Halogen separates two knobs we effectively have as one:
`HALOGEN_CTX` = the most a single request may use (default 262144, the model's full native
context), and `HALOGEN_KV_POOL_POSITIONS` = **the memory knob** — attention positions resident
*across all conversations* (default 2 x CTX, ~29.5 KiB per position). `HALOGEN_KV_SLOTS`
(default 4) is how many conversations generate at once, at ~115 MB of own state each, because
**the slots share one pool rather than each owning a copy**.

That is the architecture our `-np 3` / `--parallel` experiments were groping toward, and it
says the 256k-each-for-several-slots goal is reachable by sharing rather than by duplicating.
dsh subagents make this a real axis rather than a hypothetical one.

## Their scoreboard, for calibration

Through the full stack (chat template, tokenizer, HTTP, SSE): **812 tok/s pp2048, 1,041 pp8192**
— well below their engine-level 1,2xx figures, which is a reminder that engine benches flatter
the stack. Decode over **ten real prompt shapes**: **52.3 tok/s mean with speculation** (min
44.5 chat, max 58.4 code; 2.47 tokens committed per round). Their own instruction: *"quote the
mean with the prompt set named, never a single shape"* — the same lesson as this repo's
padding-trap finding, arrived at independently by someone shipping a product.

For calibration against us: our flash-next decode is ~20–27 tok/s, with an 8–11% noise floor.
Their 52.3 is not like-for-like (different harness, different quant, different prompt set) but
the gap is larger than the noise.

## What this changes about our plan

- **Measure the agentic loop, not just prefill.** A realistic replay — growing context, tool
  calls, a compaction — reported as per-turn latency, cache-hit fraction, and TTFT.
- **Audit the answer room first**, because it is a correctness-shaped failure that presents as
  slowness. Cheap to check: send a request whose answer cap is small while thinking is on, and
  see whether `content` comes back empty.
- **Treat "survives restart" as a first-class requirement**, and note that llama.cpp cannot do
  it today.
- **Evaluate the rival engines (gufo, pwilkin, Halogen itself) on agentic metrics**, not on
  their headline prefill: a turn-latency replay is the comparison that matters.
- **Keep the engine work.** The increment-prefill term is where our deficit actually is, and
  the tiled delta-net / direct-read work moves exactly that term.

## Caveats

- Halogen is **closed source** (`NOASSERTION`), so everything above is from its documentation,
  not from reading its implementation. Its numbers are its own.
- Its config surface is not directly portable: it is a different engine with its own
  `HALOGEN_*` knobs. The transferable part is *what it chose to tune and to measure*, not the
  values.
- It holds most of the host once loaded (~12 GB free on a 128 GB machine), and its engine port
  (8730) has **no authentication** — keep it unpublished.
