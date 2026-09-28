# Reproducing `qwen3.8-flash-next-iq4xs--gufo-rocm723-strixhalo-mtp-v1`

Everything needed to run this build on the same hardware. The build's `build.yaml` has the
measured results and the reasoning; this file is the mechanical recipe.

## Image

`ghcr.io/gufo-org/toolboxes/gufo-runtime:latest`

```sh
docker pull ghcr.io/gufo-org/toolboxes/gufo-runtime:latest
```

Engine: kyuz0's gufo, a purpose-built Strix Halo engine, NOT a llama.cpp fork. External public image - nothing is built here.

## Weights

**UD-Q4_K_XL and only that quant.** gufo's kernels implement one format set for this model and reject UD-IQ4_XS outright with `tensor blk.0.ffn_gate_exps.weight has unsupported format IQ3_S`, because UD-IQ4_XS is a *dynamic* quant whose expert tensors mix formats.

```sh
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'UD-Q4_K_XL/*' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-ud-q4-k-xl
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-mtp-shared-q8
```

111.3 GiB across four shards.

## Running it

```sh
sudo ./modelctl up --exclusive qwen3.8-flash-next-iq4xs--gufo-rocm723-strixhalo-mtp-v1
```

## Podman-isms removed

gufo's documented run command passes `--userns=keep-id` and `--group-add keep-groups`, which are podman features with no docker equivalent. Explicit numeric `group_add` replaces them in the compose here.

## Engine internals

See `knowledge/research/2026-09-27-strix-halo-engine-landscape.md`.

## Measured

See this build's `build.yaml` and, for the comparison against the other
engines, `knowledge/research/2026-09-27-strix-halo-engine-landscape.md` and
`knowledge/research/2026-09-27-halogen-agentic-tuning-lessons.md`.
