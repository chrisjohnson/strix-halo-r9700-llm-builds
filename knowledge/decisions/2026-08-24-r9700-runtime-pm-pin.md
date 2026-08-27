---
id: 2026-08-24-r9700-runtime-pm-pin
date: 2026-08-24
source: "Live debugging session on local-ai-machine (docker events oom/die loop, journalctl amdgpu resume spam, sysfs mem_info readings); fix committed as eb5faf9"
tags: [r9700, egpu, amdgpu, runtime-pm, runpm, crash-loop, qwen3.8, systemd]
status: active
---

# r9700 eGPU runtime-PM wedge kills model loads mid-stream; pinned always-on

## What happened

Both qwen3.8-27b builds on the r9700 (`q6kl` and `q4km`) were crash-looping during
model load — docker events showed a repeating `oom → die → start` cycle roughly every
50–60 s, with llama-server dying silently (exit code 0) ~45–60 s into each load attempt.
Container-level `OOMKilled` was false and there was no error output between
"loading model" and death.

The actual mechanism, visible only in the kernel log: **amdgpu was runtime-suspending
the r9700 while a live process held GPU VM allocations**, evidenced by full
PSP/SMU/GART/ring resume sequences repeating every ~10 s interleaved with:

```
amdgpu 0000:65:00.0: amdgpu: VM memory stats for proc llama-server(NNN) ... is non-zero when fini
```

Each suspend invalidated the loader's Vulkan mappings mid-load; the process died;
restart:always restarted it; repeat forever. PCIe link state (16x Gen5, no AER errors)
and thermals (~27°C) were clean throughout — a power-management wedge, not a dock/
link/hardware failure. Probable seeding event: earlier same-day processes being
OOM-killed mid-DMA during a host-memory crunch left the driver's bookkeeping wedged.

## The fix

`configuration.nix` now carries a `systemd.services.amdgpu-r9700-no-runpm` oneshot
(commit eb5faf9) that writes `on` to `/sys/bus/pci/devices/*/power/control` for every
PCI device matching vendor/device `1002:7551`, ordered `before=docker.service`,
`wantedBy=multi-user.target`. Survives reboot; re-applies on every rebuild.

Design notes baked into the unit:
- **sysfs unit, not `amdgpu.runpm=0`** — the kernel param would change PM policy for
  the Strix APU too (not implicated); scope the change to the one misbehaving card.
- **Matched by PCI ID, not cardN or BDF** — both of those can reorder across boots or
  dock replugs; the ID doesn't. Card absent → exit 0 (box boots clean without eGPU).
- Applying it live (no reboot) cleared the flap immediately — the wedge did not need a
  module reload or reboot to clear, once suspends stopped happening.

## Secondary lesson from the same session: load order matters for host RAM

The trio's standing-state math (laguna ~81 GB GTT + ornith ~23 GB + ~14 GB system floor)
leaves only a few GiB of the 124 GB budget free, by design (swapfile is the documented
pressure-relief valve). When everything was down and brought back up all-at-once,
qwen's load attempts raced laguna/ornith loads for that thin margin and lost (global
OOM picked them off). Starting **qwen first while RAM is free**, then laguna, then
ornith, loads cleanly and holds steady (~110.6 GB used, ~1.7 GB swap, all three /health
200 simultaneously).

Open consideration: after a cold boot, restart:always starts all three compose services
near-simultaneously — the race above may recur transiently until swap absorbs it. If
post-reboot qwen deaths show up again, sequencing standing-model startup (compose
healthcheck ordering or a small boot-time delay) is the known lever.
