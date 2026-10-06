# Reproducing `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-halobox-lazy-direct-budget-mmproj-effort-medium-ub8192-nocacheram-strixhalo-mtp-v1`

Everything needed to run this build. `build.yaml` has the measured results and full
reasoning; this file is the mechanical recipe.

Identical to `...-ub8192-cram14g-strixhalo-mtp-v1` (the halo-box engine-swap trial,
M-160) with one flag changed: `--cache-ram 14336` -> `--cache-ram 0`. Everything else -
engine, image, weights, KV quant, ubatch size, MTP draft head, vision projector - is
unchanged.

## Image

Same image as the cram14g build, no rebuild needed:
`strix-halo-r9700-llm-builds/halobox-strix-halo:rocm-10.0-lazy-direct`.

## Weights

Same as the cram14g build, already on disk if it has run - see that build's
REPRODUCE.md for the download commands.

## Running it

```sh
modelctl up --exclusive qwen3.8-flash-next-iq4xs--llamacpp-rocm100-halobox-lazy-direct-budget-mmproj-effort-medium-ub8192-nocacheram-strixhalo-mtp-v1
```

Port `8207` (the cram14g build is `8199` - both can coexist only with enough memory for
both; bring this one up exclusively, or stop the other first).

## Why this exists

A real system-wide OOM kill happened running the cram14g build alongside occamy
(2026-10-06, see local-ai-machine `.fleet/board` M-160 Phase 5). This build removes the
one remaining host-RAM cache this engine controls, to restore a real safety margin
against the engine's actual (higher than originally assumed) GTT footprint. See
`build.yaml` for the full margin-math writeup, including the real tradeoff this costs
(no re-prefill avoidance on session switch - this model has no `-np`-style parallelism
fallback the way occamy does).

## What's NOT yet validated here

No soak test, no measurement of the real-world cost of losing cache-ram on actual
returning sessions. This is an incident-response stopgap, not a characterized tuning
pass.
