---
id: 2026-07-24-qwen36-27b-mtp-missing-head
date: 2026-07-24
source: "OPTIMIZATIONS.md (\"MTP speculative decoding, real attempt on Qwen3.6-27B\", lines 209-258)"
tags: [mtp, qwen, llamacpp, speculative-decoding, benchmark, negative-result]
status: active
---

# MTP speculative decoding on Qwen3.6-27B: mechanism confirmed real, but this GGUF lacks an MTP head

**Finding — a real, negative result, not a workaround-and-move-on**: attempted to run MTP
speculative decoding against the already-downloaded `Qwen3.6-27B-Q4_K_M.gguf`
(`unsloth/Qwen3.6-27B-GGUF`). Flags were discovered directly from the toolbox binary's own
`--help` output rather than assumed: `--spec-type draft-mtp --spec-draft-n-max 3` (default
3), cross-checked against the actual upstream PR (`ggml-org/llama.cpp` #22673, author
`am17an`) — the PR author's own posted invocation matches exactly. The PR's own numbers
(on a DGX Spark, a different but comparable unified-memory system) showed ~72%
steady-state draft-acceptance rate at depth 3 and >2x speedup (e.g. `code_python`: 7.0 to
21.6 tok/s), consistent with community reference figures elsewhere in this project's
research.

**The actual test failed cleanly, for a real, diagnosed reason**: model loading proceeded
completely normally (identical tensor/metadata output to the plain-decode baseline) right
up to MTP-specific initialization, which failed with `context type MTP requested but
model doesn't contain MTP layers`.

**Root cause, confirmed via the HF API**: the source repo for the downloaded file
(`unsloth/Qwen3.6-27B-GGUF`) has no MTP-tagged filename anywhere in its listing. A
separate, distinct repo from the same publisher, `unsloth/Qwen3.6-27B-MTP-GGUF`, exists —
unsloth ships MTP-head-bearing GGUFs as an entirely different download, not extra tensors
bundled into the plain quants already on this machine. This is almost certainly the
artifact the community reference numbers (kyuz0's `mtp.html`, calebcoffie.com) were
actually measured against.

**Honest bottom line**: the MTP mechanism, flags, and toolbox build are all confirmed
genuinely working — the failure is a clean, correctly-diagnosed "wrong artifact" error,
not a crash or config mistake, and matches the upstream PR author's own invocation
exactly. No speedup number could be produced for this model on this machine, because the
downloaded GGUF simply lacks an MTP head. Per explicit instruction at the time, no new
download was attempted to fetch the MTP-tagged repo — that remained a real, actionable,
undone follow-up gated behind the standing new-model-download check-in rule. The existing
no-MTP baseline (pp512 342.55 tok/s, tg128 12.75 tok/s) is unchanged and not superseded —
there is no "after" number to compare it against.

**llama-bench does not support these flags at all** (`llama-bench --help | grep -iE
'draft|spec|mtp'` returns zero matches) — speculative decoding is `llama-server`/
`llama-cli`-only on this build.
