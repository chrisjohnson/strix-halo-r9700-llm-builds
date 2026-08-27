---
id: 2026-07-22-monitoring-122b-pipeline-hardening
date: 2026-07-22
source: "README.md (Decision Log — 2026-07-22 later: Monitoring wiring, 122B model, deployment pipeline hardening)"
tags: [monitoring, prometheus, grafana, vllm, benchmark, git-hygiene]
status: active
---

# 122B model benchmarked; deployment pipeline verified under real conditions; monitoring wired

**122B model downloaded and benchmarked** (`cyankiwi/Qwen3.5-122B-A10B-AWQ-4bit`, 75GB).
Run alone (no judge model, full GPU budget, `--enforce-eager` required at the time for its
AWQ kernel path — later found to be optional, see the AITER/enforce-eager decision file
if migrated), capped at 32K context vs. 131K used for other tiers. Came out slowest at
both concurrency levels — 7.87 tok/s @c1 vs 11.91/14.34 for the other two, only 16.05
tok/s @c8 with mean TTFT past 20 seconds under load. Most likely explained by
`enforce-eager` disabling CUDA graph/torch.compile — later confirmed only a marginal
factor, not the main driver (see the Phase 3 optimization decision).

**Deployment pipeline redesign (from earlier the same day) verified in production, not
just synthetic tests**: the 122B download was killed mid-transfer to test resume
behavior, a config push during the retry cycle completed in ~3.4s without disturbing it,
the download resumed from prior progress, and `docker-compose-app` correctly waited on its
marker-poll loop before running `docker compose up -d`.

**Monitoring fully wired**: Prometheus targets, Grafana provisioning/dashboard, the
`filterForward` forward-chain bug and `extraForwardRules`, fixed bridge name, LiteLLM's
`prometheus` callback.

**Process note / decided going forward**: twice this session, live-deployed changes sat
uncommitted for a while before being caught and fixed. Also caught: a multi-file `scp
<files...> host:dest/` call silently flattened `docker/prometheus/prometheus.yml` and
`docker/litellm/config.yaml` into `docker/prometheus.yml` and `docker/config.yaml` on the
target (scp doesn't preserve relative paths across multiple sources to one destination) —
masked as a "config didn't take effect" bug before being traced to the actual file
location. **Decided**: commit immediately after confirming a change works, and use
per-file destination paths (or rsync) rather than batched multi-source scp calls.
