# Reproducing `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-mmproj-effort-medium-ub8192-cram14g-strixhalo-mtp-v1`

Everything needed to run this build on the same hardware. `build.yaml` has the measured
results and the reasoning; this file is the mechanical recipe.

This is the recipe for `...-budget-mmproj-effort-medium-strixhalo-mtp-v1` (the standing
build at the time this was written) with two flags changed: `-b/-ub 16384` → `8192`, and
`--cache-ram` added at `14336` (MiB). Everything else — engine, image, weights, KV quant,
reasoning bound, MTP draft head, vision projector — is unchanged.

## Image

`strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct`

```sh
cd docker/pwilkin-strix-halo
docker build -f Dockerfile.rocm-10.0-strix-llama \
  -t strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct .
```

Same image as the base build — nothing here requires a rebuild.

## Weights

Same as the base build, already on disk if the base build has run:

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
sudo -n /run/current-system/sw/bin/modelctl up --exclusive qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-mmproj-effort-medium-ub8192-cram14g-strixhalo-mtp-v1
```

Port `8195` (the base build is `8194` — both can coexist only if there is enough memory
for both, which there is not on this box; bring this one up exclusively, or stop the base
build first, exactly as this build itself was validated).

## Why these two flags, together

See `build.yaml` for the full measurement writeup. Short version: `--parallel` (real
multi-slot concurrency) is confirmed broken on this engine two different ways, so
`--cache-ram` — a host-RAM snapshot cache that speeds up *resuming* a preempted session
without ever running two sessions' compute simultaneously — is the only lever that helps
Chris's real multi-session DSH usage. Growing `--cache-ram` costs GTT; `-ub 8192` (down
from the adopted 16384) frees roughly that much back by shrinking compute buffers, at a
measured ~6% prefill throughput cost. The split (+6 GiB cache-ram, ~1 GiB banked as extra
margin rather than spent) was Chris's explicit choice, after checking the box's real
sustained memory floor (not a post-restart snapshot) via Prometheus history.

## Two non-obvious things carried from the base build, either of which stops it dead

- **`HSA_OVERRIDE_GFX_VERSION` is forced empty.** The image bakes `11.5.1`, and on this
  box that makes ROCr find no device at all. Verified with `--list-devices`: `11.5.1` →
  none, empty → `ROCm0: Radeon 8060S`.
- **Devices are declared `/dev/kfd:/dev/kfd` and `/dev/dri:/dev/dri`**, not as bare
  paths — a bare `- /dev/dri` passes an empty device list.

## What's NOT yet validated here (be aware before promoting)

- A real multi-hour soak test of steady-state memory impact. The occamy incident
  happened because a cache-ram cap was sized against a moment-in-time reading, not
  observed behavior over hours — the same discipline applies here.
- A real demonstration that a `--cache-ram` hit actually speeds up resuming a preempted
  session (vs. just confirming the flag is accepted and the server loads/serves).

## Measured

See this build's `build.yaml` for the -ub/-b sweep numbers and the multi-slot
investigation. See `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-ub4096-strixhalo-mtp-v1`
for the rejected `-ub 4096` data point.
