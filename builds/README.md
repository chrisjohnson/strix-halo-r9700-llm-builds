# builds/ — llm-inference-bench stack (M-101)

> ## 📊 Interactive model comparison dashboard
>
> **→ [local-ai-machine interactive dashboard](https://chrisjohnson.github.io/local-ai-machine/interactive-dashboard.html)**
>
> This directory's benchmark results feed an interactive, artificialanalysis.ai-style
> dashboard: bar chart of output tokens/s per build, "best build per model" + engine /
> dense-MoE / context / concurrency filters, and a per-model detail view with every build's
> notes, full benchmark matrix, and docker-compose. Regenerate it after a new sweep with
> `python3 scripts/generate_interactive_dashboard.py`.

This top-level directory is the benchmark stack (formerly deliberately
separate from `catalog/`, the old stack's catalog — that stack and its
`scripts/benchmark_orchestrator.py` were deleted 2026-08-20; this is the
only one now). One directory per build, named exactly after the build's
docker-compose service name:

```
builds/
  qwen3.6-27b--vllm-therock-gfx1151-strix-apu-v1/
    build.yaml              # hand-authored build identity (see below)
    docker-compose.yaml     # directly-executable compose file for this build
    benchmarks/
      llm-inference-bench/
        <timestamp>.json       # raw structured output (untainted, never edited)
        <timestamp>-stdout.log # tool stdout (captured progress/errors)
        <timestamp>-crash.log  # docker logs from a twice-crashed container
```

## Layout invariants (M-102)

The **global** `docker/docker-compose.yml` and the per-build files are **1:1**:
every build directory has a `build.yaml` **and** a `docker-compose.yaml`, and
every model service in the global compose has a build directory (and vice
versa). If a service name changes or a build is added, update BOTH the global
compose and the build directory.

`builds/<name>/docker-compose.yaml` is the *verbatim* service block from the
global compose (same service name, same container_name, same image, command,
ports, volumes) wrapped in a project header. It is directly executable:

```
docker compose -f builds/<name>/docker-compose.yaml up -d
```

The project name is pinned to `docker` (the same project the global stack
uses), and any named volumes it references are declared `external` with their
full `docker_<volume>` names — so running a build file standalone attaches the
*same* volumes the global stack uses (model stores, vLLM cache dirs). The
per-build files are machine-generated from the global compose so they cannot
drift; treat the global compose as the source of truth.

## build.yaml

Hand-authored per build by a human/agent — the orchestrator NEVER writes it.
It carries the derived metadata, a `status:` note, and optional `bench:` CLI
overrides for the harness invocation. A missing build.yaml is fine — the build
still benchmarks using the default matrix.

```yaml
name: qwen3.6-27b--vllm-therock-gfx1151-strix-apu-v1   # == compose service name
status: WORKING                              # catalog status: WORKING / BROKEN /
                                             # TESTED_VIABLE / TESTED_NOT_VIABLE /
                                             # UNTESTED-BUT-DOWNLOADED
derived:
  engine: vllm-therock-gfx1151-v1            # engine ref from catalog/engines
  model: Qwen3.6-27B
  params: 27B
  active_params: null
  quant: bf16
  mtp: false
  dflash: false
  notes: >-
    any hand-authored context about this build
bench:                 # optional overrides; all keys optional
  concurrency: "1,2,4,8"
  contexts: "0,16384,32768,65536"
  duration: 30
  max_tokens: 8192
  kv_budget: 0          # 0 = auto/no limit; see llm_decode_bench.py --help
  model: qwen3.6-27b    # override the tool's auto-detected model id if needed
```

The `compose:` inline block that older build.yamls carried was removed in
M-102 — that definition now lives in `docker-compose.yaml` in the same
directory. `status:` is a first-class field so that BROKEN / other-machine
builds can stay in the catalog and in the compose stack without looking
healthy. Ollama builds set `bench.model` to the registered ollama model name
(it differs from the service name); the shared `ollama_data` volume carries
the model store across all dedicated per-build ollama instances.

Raw benchmark JSON is preserved byte-for-byte as written by the tool ("raw
untainted"). The orchestrator's own run/commit context is the only place the
true engine is recorded (the tool labels llama.cpp builds "sglang (assumed)"
because it only understands vllm:/sglang: Prometheus metrics and falls back
to client-side timing — the numbers are valid, the label is not).

## Queuing runs — the orchestrator API

Runs are enqueued and monitored over the orchestrator's JSON API — never by
tailing container logs. **`docs/benchmark-api.md` is the reference**: `POST
/run` to enqueue, then poll `GET /runs/<id>` (a small JSON doc) until
`status` is `done`/`failed`; consume `GET /runs/<id>/log?stream=1` (SSE) for
live progress. Enqueueing is also available from the web UI
(`http://192.168.1.226:8092/`). Remember: a run stops every non-target model
service, so restore what was serving before the run afterwards
(`docker compose up -d <svc>` on the box).
