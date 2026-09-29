# Reproducing `occamy-1.0-mtp-q5--llamacpp-vulkan-radv-r9700-mtp-v2`

Everything needed to run this build on the same hardware. The build's `build.yaml` has the
measured results and the reasoning; this file is the mechanical recipe. Identical to v1's
recipe in every way except `--cache-ram` (see `build.yaml` for why).

## Image

`docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv`

```sh
docker pull docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv
```

Engine: llama.cpp compiled for Vulkan RADV on gfx1151. External public image - nothing is built here.

## Weights

Weights under `/var/lib/ai-models/`, declared in `local-ai-machine`'s `configuration.nix` `models` list:

```sh
/var/lib/ai-models/occamy-1.0-mtp-q5/occamy-1.0-mtp-Q5_K_M.gguf   # one file
/var/lib/ai-models/occamy-1.0-mmproj/                              # vision projector
```

## Running it

```sh
sudo -n /run/current-system/sw/bin/modelctl up --exclusive occamy-1.0-mtp-q5--llamacpp-vulkan-radv-r9700-mtp-v2
```

This is the **R9700** (Vulkan) build: `card0`. ROCm's device numbering is the OPPOSITE of Vulkan's, so a `-dev ROCm0` in a Vulkan build does not mean the same GPU as `ROCm0` in a ROCm build.

## Engine internals

See `knowledge/research/2026-09-27-strix-halo-engine-landscape.md`.

## Measured

See this build's `build.yaml`, v1's `build.yaml` (everything except `--cache-ram` carries
over unchanged), and `knowledge/research/2026-09-29-occamy-cache-ram-midnight-hang.md`
(local-ai-machine repo) for the incident that prompted the `--cache-ram` trim.
