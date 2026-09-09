---
id: 2026-09-09-r9700-medium-dense-throughput-decay
date: 2026-09-09
source: "Live investigation on local-ai-machine (docker logs, rocm-smi, a direct /v1/chat/completions timing test, and a controlled modelctl down/up restart); conversation session that also produced the reasoningEfforts work in dsh-deploy PR #2"
tags: [r9700, egpu-dock, dirk, qwen3.8, medium-dense, throughput, prefill, vram, amdgpu, modelctl]
status: active
---

# Dirk (medium-dense) prefill throughput decays ~5x over days of uptime; VRAM footprint stays flat; a restart fully recovers it

## What was decided

No automated mitigation for now. Restart the build manually (`modelctl down
<id>` / `modelctl up <id>`) if throughput on `medium-dense`
(`dirk-qwen3.8-27b-q6kxl--llamacpp-vulkan-radv-r9700-mtp-v4`) looks
degraded — a restart is confirmed to fully recover it. A periodic restart
timer (the same pattern already used for the unrelated 2026-08-24
runtime-PM issue, `amdgpu-r9700-no-runpm-periodic.timer`) was proposed and
explicitly declined by Chris (2026-09-09).

## Why

Only three uptime/throughput data points exist so far (fresh boot, ~36h,
~2 days — see Evidence below), not enough to size a safe restart interval
without guessing. The manual fix is cheap enough to apply on demand once
noticed, and automating a restart cadence on this little data risks either
restarting too aggressively (interrupting real work for no benefit) or too
loosely (false confidence that the problem is "handled"). Revisit once
either the decay rate is better characterized or this causes real
production impact (a timeout/crash) before someone notices manually.

## Alternatives considered

- **Periodic restart timer**, mirroring `amdgpu-r9700-no-runpm-periodic.timer`.
  Rejected for now per the reasoning above — not that the pattern is wrong,
  just premature with this little data.
- **Reduce VRAM footprint structurally** (drop `--mmproj`, shrink `-c`, or
  shrink `--cache-ram`) to widen the margin. Not attempted — the decay
  itself doesn't correlate with VRAM footprint (see Evidence), so this
  would address the pre-existing tight baseline, not the decay. Worth
  revisiting separately if the baseline tightness itself becomes a problem
  (see "Baseline tightness, separate from the decay" below).

## Evidence

Investigation was triggered by Chris noticing `medium-dense` feeling
slower during an unrelated reasoning-effort test
([dsh-deploy PR #2](https://github.com/chrisjohnson/dsh-deploy/pull/2)),
suspecting the reasoning-effort dropdown might be silently stuck on
`xhigh` (ruled out — confirmed via the session's own event log that
`reasoningEffort` was never set in that session at all).

- **Fresh boot** (from the container's own startup log, captured ~5 days
  into its uptime by then): prompt processing 750-900+ tok/s (task 24:
  4096 tok in 4.55s @ 900.88 tok/s, progressing to 749.52 tok/s, aggregate
  eval 711.36 tok/s over 5344 tokens).
- **~36h into that same uptime** (2026-09-08, during the reasoning-effort
  investigation): degraded to ~240-250 tok/s. Two client-side
  `pi-ai stream idle timeout after 300000ms` failures happened on
  large-context requests before a retry succeeded — that retry only
  succeeded because it hit a large (168,350-token) cache hit and needed
  almost no fresh prefill; the two failed attempts both needed substantial
  fresh prefill at the degraded rate.
- **~2 days into uptime** (2026-09-09, this investigation): further
  degraded to ~150-180 tok/s, plus another cancelled task during a live
  session.
- **VRAM usage measured identical before and after a clean restart**:
  32.8GB / 34.2GB used (~1.4GB free) both times (`rocm-smi --showmeminfo
  vram`). This rules out VRAM footprint growth as the cause — whatever is
  degrading, it isn't consuming more bytes to do it.
- **Controlled restart test**: `modelctl down
  dirk-qwen3.8-27b-q6kxl--llamacpp-vulkan-radv-r9700-mtp-v4` confirmed
  VRAM fully freed (60MB residual) before bringing it back with `modelctl
  up`. A real ~7.2k-token `/v1/chat/completions` request sent immediately
  after reload measured 907.06 → 880.59 → 845.14 → 848.27 tok/s
  (aggregate prompt-eval 767.69 tok/s) — back in the original fresh-boot
  range, not a partial recovery.

### What this rules out

- **Not a VRAM leak** in the ordinary sense — byte count is flat
  before/after restart, only speed differs.
- **Not the same mechanism as the 2026-08-24 runtime-PM wedge**
  (`knowledge/decisions/2026-08-24-r9700-runtime-pm-pin.md`) — that one
  causes load-time crash loops from the card runtime-suspending mid-load;
  this is steady-state throughput decay while serving normally, with no
  crashes. Different symptom, likely different mechanism, though both are
  real amdgpu/RDNA4-on-this-card quirks.
- **Root cause of the decay itself is NOT identified** — GPU-side
  allocator/descriptor-pool state, thermal, or another driver quirk in the
  same family as the already-documented (but since lost — see below)
  `gtt-accounting-leak-on-exit` bug are all plausible; only the
  restart-recovers-it fact is confirmed, not the mechanism.

### Baseline tightness, separate from the decay

Independent of the decay: this build runs with very little VRAM headroom
even at a perfectly fresh boot. `common_fit_params: failed to fit params
to free device memory: n_gpu_layers already set by user to 999, abort`
appears in the startup log immediately, every time — llama.cpp's own
auto-fit logic flags this config (Q6_K_L weights + full `-c 262144` +
`-ctk/-ctv q4_0` + `--mmproj mmproj-F16.gguf` vision adapter) as not
comfortably fitting, and only proceeds because `-ngl 999` forces full GPU
offload regardless. The original VRAM figure recorded when this Q6_K_L
build was first promoted (2026-08-22, ~28.01GB/31.86GB used, ~3.85GB free)
predates `--mmproj` being added to this build (2026-09-02) — today's
~32.8GB baseline is plausibly explained by that addition, but this was
never re-verified at the time mmproj was added. Treat that as a
plausible-not-confirmed explanation for the baseline tightness
specifically — a separate question from the decay this note is actually
about.

### Aside: lost documentation

While investigating, found that an earlier, real, related finding —
`gtt-accounting-leak-on-exit`, documented in `local-ai-machine`'s
`catalog/hardware.yaml` as of commit `5926c22` (2026-08-20: a real,
reproducible amdgpu kernel bug reporting phantom "used" GTT after a
process touching this GPU exits, confirmed via `free -h` to be a stats
bug, not a real leak) — was deleted from `local-ai-machine` in commit
`fc09501` during the catalog extraction to this repo, and never migrated
here. It no longer exists in either repo. Not restored as part of this
note (out of scope — this note is about a different symptom), but
flagging so it isn't assumed to still be tracked somewhere.

## If this happens again

1. `curl <build-port>/slots` — compare `n_prompt_tokens_processed` growth
   against wall-clock time for a rough tok/s read, or `docker logs
   <container> --tail 20` for the server's own `print_timing` lines.
2. `rocm-smi --showmeminfo vram` before assuming VRAM growth — it was flat
   in this instance; don't skip this check and assume otherwise.
3. If throughput has genuinely dropped versus this note's fresh-boot
   numbers (750-900+ tok/s prefill on this exact build): `modelctl down
   <build-id>` then `modelctl up <build-id>` — confirmed to fully restore
   it, no other remediation needed. Only tested against this specific
   build; treat as a working hypothesis, not a confirmed fact, for other
   R9700 builds until observed there too.
