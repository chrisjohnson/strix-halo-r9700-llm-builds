---
id: 2026-07-24-llama-server-concurrent-serving-gap-and-bugs
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"Fourth pass — Lead 1: llama-server concurrent/parallel serving\", lines 296-319)"
tags: [llamacpp, concurrency, rocm, vulkan, gfx1151, bug, benchmark]
status: active
---

# llama-server concurrent serving: real untested gap, plus a live data-corruption bug on this exact chip

**Finding — the toolbox image bundles `llama-server`**, confirmed directly on the actual
remote box (not a local Mac docker pull, which would test the wrong architecture):
`/usr/bin/llama-server`, same build as the existing benchmarks (version 10107,
`c0bc8591e`).

**Real, confirmed flags for concurrent serving** (from the binary's own `--help`): `-np,
--parallel N` (server slots, default -1 = auto — turns on multi-client continuous
batching), `-cb, --cont-batching` (enabled by default), `-kvu, --kv-unified` (single
unified KV buffer, default enabled when slots is auto — implicated in the bug below),
`--cache-idle-slots`, `--slots`/`--no-slots` (exposes a `/slots` monitoring endpoint).

**No existing benchmark data for `llama-server` multi-client throughput existed anywhere
checked at the time** — confirmed by directly parsing kyuz0's raw `results.json` (554
runs, all single-stream `llama-bench` metrics, no concurrency field in the schema at all)
and kyuz0's own `run_benchmarks.sh` (invokes only `llama-bench`, never `llama-server`).

**A real, currently-open, actively-being-fixed data-corruption bug affects exactly this
scenario on exactly this chip.** `ggml-org/llama.cpp#25992` ("server -np 4 --kv-unified
returns other requests' responses verbatim on integrated HIP GPU (gfx1151)"), opened
2026-07-22. Under concurrent mixed load (`-np 4 --kv-unified`) on an HIP/ROCm backend
integrated GPU, `llama-server` returns complete responses that verbatim belong to a
different, earlier request — bisected to a specific commit that re-enabled a direct
ROCm-host compute path previously disabled for exactly this corruption class. Confirmed
by four independent reporters, all on this same chip family (including one on the exact
same GMKtec EVO-X2/Ryzen AI Max+ 395/Radeon 8060S/128GB hardware as this box), one
explicitly reporting it breaking Qwen tool calling from agent harnesses.

**Critical mitigating fact**: every reporter confirms switching to the Vulkan backend
fixes it. This project's toolbox image is `kyuz0/amd-strix-halo-toolboxes:vulkan-radv` —
Vulkan/RADV, not HIP/ROCm — so this specific bug should not affect us directly. A fix PR
(`ggml-org/llama.cpp#25863`) was open and awaiting review at time of writing.

**A second, separate, gfx1151/RADV-Vulkan-specific concurrency bug was also found, but is
old, unresolved, and was auto-closed for staleness** — `ggml-org/llama.cpp#20906` ("Slot
gets stuck after batch processing... when 2 requests running concurrently"), filed
directly against RADV GFX1151. Never actually fixed; GitHub's bot auto-closed it for
14-day inactivity, not because anyone confirmed a resolution.

**Net assessment**: `llama-server --parallel N --cont-batching` was a genuine, previously
untested capability on this exact toolbox image at time of writing. Any real attempt
should specifically validate output correctness under concurrency (not just throughput),
given the dodged-but-recent HIP corruption bug and the older unresolved Vulkan slot-hang
report on this identical backend/hardware combination. See
`2026-07-24-llama-server-concurrent-serving-results.md` for the actual benchmark run that
followed up on this finding.
