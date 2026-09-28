# Reproducing `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-cacheram-strixhalo-mtp-v1`

Everything needed to run this build on the same hardware. The build's `build.yaml` has the
measured results and the reasoning; this file is the mechanical recipe.

## Image

`strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct`

```sh
cd docker/pwilkin-strix-halo
docker build -f Dockerfile.rocm-10.0-strix-llama \
  -t strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct .
```

Engine: `pwilkin/llama.cpp` branch `strix-halo` on a custom retained-PM4 ROCr/HIP runtime built from `pwilkin/rocm-systems` branch `ilintar-experiments`, over ROCm 10.0. Both upstream commits are **pinned** in the Dockerfile. Takes 40-60 min and several GB. The build self-gates: it runs `test-backend-sched-ring`, greps `DEBUG_HIP_GRAPH_PM4` out of the built `libamdhip64.so`, and `ldd`-checks the custom libraries.

## Weights

This model's weights, all under `/var/lib/ai-models/` and declared in `local-ai-machine`'s `configuration.nix` `models` list:

```sh
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'UD-IQ4_XS/*' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-iq4xs
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-mtp-shared-q8
```

Note the **nested `MTP/` path**: `hf download` preserves the repo's directory structure, so the file lands at `<dir>/MTP/mtp-...gguf` and the compose mount says so. It is the **shared** head; the non-shared file is a different head and is what the EngramHalo builds use. `mmproj-BF16.gguf` (908 MB) is this model's vision projector and is not mounted here.

## Running it

```sh
sudo ./modelctl up --exclusive qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-cacheram-strixhalo-mtp-v1
```

## Two non-obvious things, either of which stops it dead

Both are already handled in this build's `docker-compose.yaml`, with the evidence in comments there:

- **`HSA_OVERRIDE_GFX_VERSION` is forced empty.** The image bakes `11.5.1`, and on this box that makes ROCr find **no device at all** — `ggml_cuda_init: failed to initialize ROCm: no ROCm-capable device is detected`, then `invalid device: ROCm0`. Verified one variable at a time with `--list-devices`: `11.5.1` → none, empty → `ROCm0: Radeon 8060S`, `11.0.0` → none. gfx1151 is native on ROCm 10.0 here, so the override is both unnecessary and fatal. This is a host-specific setting baked into a shared image.
- **Devices are declared `/dev/kfd:/dev/kfd` and `/dev/dri:/dev/dri`**, not as bare paths. A bare `- /dev/dri` looks equivalent and passes an **empty** `/dev/dri`, which produces the same no-device failure.

Two more, from the same engine's own documentation:

- **Never set `GGML_CUDA_ENABLE_UNIFIED_MEMORY`.** It routes allocation through `hipMallocManaged`, and under HIP graphs the MTP draft context corrupts — garbage tokens, or the server dying with `init: invalid token`.
- **No host networking under rootless docker.** It masks `/sys`, `/sys/class/kfd` disappears, and ROCr reports no device even with `/dev/kfd` passed through. This build publishes a port.

## Engine internals

See `docker/pwilkin-strix-halo/README.md`.

## Measured

See this build's `build.yaml` and, for the comparison against the other
engines, `knowledge/research/2026-09-27-strix-halo-engine-landscape.md` and
`knowledge/research/2026-09-27-halogen-agentic-tuning-lessons.md`.
