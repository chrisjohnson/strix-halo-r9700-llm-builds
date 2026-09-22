---
id: 2026-09-22-dirk-aspm-ubatch-sweep-no-win
date: 2026-09-22
source: manual A/B sweep against the running dirk-qwen3.8-27b-q6kxl--llamacpp-vulkan-radv-r9700-mtp-v10 build
tags: [dirk, qwen3.8-27b, r9700, aspm, ubatch, benchmark, tested-not-viable]
status: active
---

# dirk tuning sweep: PCIe ASPM policy and -ub (ubatch) — neither helps

## Finding

Prompted by an external chatbot's (unverified) claim that an Apple M6 Mac Mini's ~53
tok/s vs this box's ~35-52 tok/s on Qwen3.8-27B was explained by fixable Vulkan/RADV
driver overhead. Most of that chatbot's specific claims were independently false or
already contradicted by this repo's own data (ROCm already TESTED_NOT_VIABLE here,
vLLM already measured worse than the standing build — see git history around
2026-09-22). Two claims were plausible enough to actually test:

**PCIe ASPM policy (default vs performance)**: no meaningful difference.
5x 400-token single-stream decode runs each, same dirk command otherwise unchanged:

| policy | runs (tok/s) | avg |
|---|---|---|
| default | 44.4, 45.6, 45.7, 48.9, 49.6 | 46.85 |
| performance | 48.7, 49.9, 43.9, 46.8, 49.1 | 47.68 |

~1.8% apart, inside the run-to-run noise band (each config's own spread is 4-6
tok/s). ASPM link power states matter for idle-to-active transition latency, not
sustained decode where the link stays active throughout — this workload never
exercises the thing ASPM policy changes. Reverted to `default` (performance-mode
buys nothing here and costs power/heat).

**`-ub` (ubatch size)**: unset/default (effectively 512) is at least as good as
every larger value tried; going bigger consistently hurts:

| -ub | runs (tok/s) | avg |
|---|---|---|
| unset (default) | 44.4, 45.6, 45.7, 48.9, 49.6 | 46.85 |
| 256 | 49.2, 48.5, 41.7, 48.7, 45.9 | 46.79 |
| 1024 | 39.4, 37.2, 35.5, 40.1, 43.3 | 39.11 |
| 2048 | 42.2, 37.9, 45.1, 42.8, 43.0 | 42.20 |

Community guidance (llama.cpp RDNA4 discussion #21043) suggesting 288-2048 as a
"recommended" ubatch range does not hold for this workload — that guidance is
prefill/batch-throughput oriented; dirk's MTP setup here is single-stream (`-np 1`)
decode-bound, where a larger ubatch just adds compute-buffer overhead per step with
no batching to amortize it against. No config change made — the build was already
running with `-ub` unset.

## Methodology

Ad hoc `docker run` of the same image/mounts/devices as the production compose file
(`docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv`, same GGUF + mmproj, same
`--spec-type draft-mtp --spec-draft-n-max 4 --spec-draft-p-min 0.6` flags), on a
throwaway container name/port so the real `dirk-...-mtp-v10` compose service could be
cleanly stopped (`modelctl down`) and restarted (`modelctl up`) around the test
window — avoids GPU contention between the test container and production. Each
config: `/health` poll until ready, one 64-token warmup request (discarded), then 5x
400-token `/completion` requests against a fixed prompt, reading
`timings.predicted_per_second` from each response. 200-token runs were tried first
and were far noisier (25%+ spread) — 400 tokens was enough to tighten the spread to
~10-15%.

Toggling ASPM needed a persistent mechanism since there's no standing sudo grant for
arbitrary sysfs writes: added `pcie-aspm-performance`/`pcie-aspm-default` oneshot
systemd units to `local-ai-machine/configuration.nix` (manual-trigger only, not
`wantedBy` anything, so they never auto-apply) — see that repo's commit
"Add manual-trigger ASPM policy toggle for r9700 tuning A/B test". Left in place as
inert manual toggles in case they're useful for a future test; current live policy is
`default`.

## Conclusion

No change to the standing dirk build. Both `-ub` and ASPM tuning are ruled out as
levers for this specific single-stream MTP decode workload on the r9700 eGPU. The
M6-vs-R9700 gap (if it's even apples-to-apples — no comparable M6 config/quant was
ever documented) isn't explained by a fixable local misconfiguration; the earlier
DFlash2/ROCm/vLLM alternatives were already ruled out too. Nothing left on this
specific thread worth pursuing without a genuinely new lead.
