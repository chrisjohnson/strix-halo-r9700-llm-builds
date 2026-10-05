# Reproducing `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-mmproj-effort-medium-ub2048-cram14g-strixhalo-mtp-v1`

Everything needed to run this build. `build.yaml` has the measured results and the
full reasoning; this file is the mechanical recipe.

This is `...-budget-mmproj-effort-medium-ub8192-cram14g-strixhalo-mtp-v1` (the standing
build at the time this was written) with one flag changed: `-b/-ub` from `8192` to
`2048`. Everything else — engine, image, weights, KV quant, cache-ram, reasoning bound,
MTP draft head, vision projector — is unchanged.

## Image

Same image as the standing build, no rebuild needed:
`strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct`.

```sh
cd docker/pwilkin-strix-halo
docker build -f Dockerfile.rocm-10.0-strix-llama \
  -t strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct .
```

## Weights

Same as the standing build, already on disk if it has run:

```sh
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'UD-IQ4_XS/*' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-iq4xs
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-mtp-shared-q8
```

`mmproj-BF16.gguf` at `/var/lib/ai-models/qwen3.8-flash-next-mmproj/` is this model's
vision projector, mounted at `/mmproj`.

## Running it

```sh
sudo -n /run/current-system/sw/bin/modelctl up --exclusive qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-mmproj-effort-medium-ub2048-cram14g-strixhalo-mtp-v1
```

Port `8198` (the standing build is `8195` — both can coexist only with enough memory
for both; bring this one up exclusively, or stop the standing build first, same as how
this build was itself validated).

## Why this exists

The standing build crash-OOMs once an image enters a long, deep conversation — confirmed
twice in real production use. See `build.yaml` for the full root-cause writeup and
`knowledge/research/2026-10-05-qwen4exp-mtp-vision-oom.md` for the complete investigation,
including a fix attempt that was tried and reverted (proved the crash's cause is total
work, not chunking granularity) and a real code-level fix that was identified but not
attempted (too much correctness risk to rush). `-ub 2048` is the validated mitigation:
no code patch, confirmed safe up to 98% of the model's full context depth, at a real
~43% prefill speed cost.

## Two non-obvious things carried from the standing build, either of which stops it dead

- **`HSA_OVERRIDE_GFX_VERSION` is forced empty.** The image bakes `11.5.1`, and on this
  box that makes ROCr find no device at all.
- **Devices are declared `/dev/kfd:/dev/kfd` and `/dev/dri:/dev/dri`**, not as bare
  paths — a bare `- /dev/dri` passes an empty device list.

## What's NOT yet validated here

A real multi-hour soak test of steady-state memory behavior under mixed real usage. The
crash-fix itself is validated (pushed to 98% of max context depth, no crash) — this is
about confirming nothing else drifts under sustained real traffic, same discipline the
occamy incident and the original `ub8192-cram14g` promotion both required before standing
promotion.

## Measured

See this build's `build.yaml` for the full investigation and measurements, and
`knowledge/research/2026-10-05-qwen4exp-mtp-vision-oom.md` for the engine-level writeup
portable beyond this specific build.
