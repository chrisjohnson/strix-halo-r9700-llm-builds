# builds/ — model-engine build catalog

> ## 📊 Interactive model comparison dashboard
>
> **→ [interactive dashboard](https://chrisjohnson.github.io/strix-halo-r9700-llm-builds/)**
>
> This directory's benchmark results feed an interactive, artificialanalysis.ai-style
> dashboard: bar chart of output tokens/s per build, "best build per model" + engine /
> dense-MoE / context / concurrency filters, and a per-model detail view with every build's
> notes, full benchmark matrix, and docker-compose. Regenerate it after a new sweep with
> `python3 scripts/generate_interactive_dashboard.py` (CI regenerates and republishes it
> automatically on every push to main).

One directory per build, named exactly after the build's docker-compose
service name:

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

## Ports

Per-engine-family, sequential within family:

- vLLM builds: 8000-8099
- llama.cpp-server: 8100-8199
- Ollama: 11434 (single shared instance, model switch via API) plus
  dedicated per-build instances above 11434 for benchmarking
- Everything binds to 127.0.0.1 only

## `docker-compose.yaml` — each build is its own standalone compose project

`builds/<name>/docker-compose.yaml` is directly executable, and is the
**sole** source of truth for that build — there is no shared/global
compose file duplicating it, and nothing here gets "generated from"
anything else. `modelctl` and `llm-inference-bench`'s own orchestrator
both operate on these files directly, one project per build:

```
docker compose -p <name-with-periods-replaced-by-underscores> -f builds/<name>/docker-compose.yaml up -d
```

The `-p` override matters: every build's compose file declares `name:
docker` (a leftover from when a single project actually was shared across
every build), so without an explicit `-p` per invocation, every build
would collide into one Compose project and its default network — see
`modelctl`'s own `project_name_for()` for the exact transform (periods
become underscores; Compose's project-name validator rejects periods
outright, and build ids commonly carry version-number periods like
"qwen3.8"). Any named volume a build references is declared `external:
true` with its real fixed name (e.g. `docker_vllm-gpt-oss-120b-cache`) —
`external: true` bypasses project-name prefixing entirely, so this still
resolves to the same real volume regardless of which project name control
this build through.

Two builds — the same three build.yaml `status:` builds currently in the
standing set — additionally carry `restart: always` plus a
`com.local-ai-machine.always-up: "true"` label, so they self-heal and are
recognized as "don't cycle for GPU exclusivity, just health-check"
targets by `llm-inference-bench`'s orchestrator. See `local-ai-machine`'s
own `standing-models.txt` and `configuration.nix`'s
`standing-models-boot` unit for how the boot-time set is actually chosen
and brought up — that policy lives there, not here.

## GPU co-residency

At most one vLLM + one llama.cpp-server build can usually co-reside on
one GPU without contention; Ollama's footprint is small enough to be safe
alongside either. `--gpu-memory-utilization`: judge-sized models (roughly
<25B, the ones almost always run co-resident alongside a larger candidate
model) should carry an explicit low cap (e.g. 0.20) so they don't starve
whatever they're running alongside — vLLM's default (0.90) assumes it
owns the whole GPU, which is only true for a standalone candidate.

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
