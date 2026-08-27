---
id: 2026-07-22-benchmark-deploy-pipeline-hardware-audit
date: 2026-07-22
source: "README.md (Decision Log — 2026-07-22, Benchmark pass, deployment pipeline redesign, hardware/system audit)"
tags: [vllm, deployment, nixos, systemd, security, hardware]
status: active
---

# Deployment pipeline redesign and hardware audit fixes

**Decided**: switch the download/compose systemd units to timer-triggered
(`systemd.timers`, `OnBootSec`) with `restartIfChanged = false`, and make
`docker-compose-app` poll the downloads' `.download-complete` marker files rather than
using `after=`/`wants=` unit ordering against them.

**Why**: `nixos-rebuild switch` blocks synchronously on starting/restarting any
long-running systemd unit — a multi-GB model download turned unrelated config pushes into
15-40 minute stalls. Arming a timer is near-instant regardless of the triggered work's
duration. Ordering against download units directly would only prove "the most recent
attempt exited," not "eventually succeeded," since they retry indefinitely on failure.
Verified end-to-end: killed an in-flight download mid-transfer, pushed a config change,
confirmed the switch completed in ~3.4 seconds (not 15-40 minutes), and confirmed the
download resumed rather than restarting from scratch.

**Related fix, same pass**: `hf download`'s exit code is not reliable evidence of
completeness (observed directly — a "complete" 35B download was missing 6 of 26 shards).
The download script now cross-checks `.incomplete` markers and sharded models' manifests
instead of trusting the exit code alone.

**Hardware/system audit findings and fixes** (same session):
- CPU governor stuck on `powersave` on all 32 threads — fixed to `performance`.
- Intermittently-timing-out router DNS resolver — fixed with fallback resolvers plus
  `networking.networkmanager.dns = "none"` (NetworkManager was silently ignoring
  `networking.nameservers` otherwise).
- `rocm-smi`'s VRAM metric is effectively useless on this unified-memory APU — added
  `amdgpu_top`/`nvtopPackages.amd` plus missing common shell tools.
- **Real security gap found and fixed**: Docker's own FORWARD-chain iptables rules bypass
  NixOS's firewall entirely for published container ports — confirmed directly, port 8000
  (raw vLLM, zero auth) was externally reachable despite never being in
  `allowedTCPPorts`. Fixed with `networking.firewall.filterForward = true` (required
  switching to the nftables backend). Ports 8000/8001 deliberately excluded from the
  allowlist going forward; LiteLLM on 4000 remains the only intended authenticated
  gateway. (Note: this fix was later found to be incomplete — see
  `2026-07-23-firewall-loopback-binding-fix.md` for the real, complete fix.)

**Benchmark pass results (same session, for context)**: first real `vllm bench serve`
runs across the 35B primary, 4B judge, and GPTQ 80B comparison models at concurrency 1 and
8 (`docs/benchmark-report-2026-07-22.html`). No clean speed winner — GPTQ 80B won
single-stream (14.34 vs 11.91 tok/s) with more consistent latency, 35B bf16 won at
concurrency 8 (33.19 vs 26.13 tok/s). Counterintuitive footprint finding: the 80B GPTQ
model is smaller on disk and leaves more KV cache headroom than the 35B bf16 model
(46.49GiB weights/40.42GiB KV vs 66.97GiB weights/18.49GiB KV) — quantization beat raw
parameter count for memory footprint.
