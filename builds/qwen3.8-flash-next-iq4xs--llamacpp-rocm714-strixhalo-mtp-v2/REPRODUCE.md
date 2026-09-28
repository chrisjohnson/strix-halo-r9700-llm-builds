# Reproducing `qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v2`

Everything needed to run this build on the same hardware. The build's `build.yaml` has the
measured results and the reasoning; this file is the mechanical recipe.

## Image

`strix-halo-r9700-llm-builds/qwen4exp-strix-halo-mtp:rocm-7.14`

```sh
cd docker/qwen4exp-strix-halo-mtp
docker build -f Dockerfile.rocm-7.14 \
  -t strix-halo-r9700-llm-builds/qwen4exp-strix-halo-mtp:rocm-7.14 .
```

Engine: `Aristo94/EngramHalo.cpp` branch `strix-halo-qwen4exp`, third-party. This Dockerfile does NOT pin a commit - it clones the branch head - plus two vendored patches applied conditionally. ROCm 7.14 for gfx1151.

## Weights

This model's weights, all under `/var/lib/ai-models/` and declared in `local-ai-machine`'s `configuration.nix` `models` list so a systemd unit fetches them rather than a human:

```sh
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'UD-IQ4_XS/*' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-iq4xs
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'MTP/mtp-Qwen3.8-Flash-Next-Q8_0.gguf' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-mtp-q8
```

Also available and **not mounted** here: `mmproj-BF16.gguf` (908 MB), this model's vision projector.

## Running it

```sh
sudo ./modelctl up --exclusive qwen3.8-flash-next-iq4xs--llamacpp-rocm714-strixhalo-mtp-v2
```

## Running it

```sh
sudo ./modelctl up --exclusive <this build id>     # waits for /health, then primes
```
`up` waits for health and then sends a priming completion, so the first real request does not pay start-up cost. Every build has its own host port, taken from its own compose.

## Engine internals

See `docker/qwen4exp-strix-halo-mtp/README.md`.

## Measured

See this build's `build.yaml` and, for the comparison against the other
engines, `knowledge/research/2026-09-27-strix-halo-engine-landscape.md` and
`knowledge/research/2026-09-27-halogen-agentic-tuning-lessons.md`.
