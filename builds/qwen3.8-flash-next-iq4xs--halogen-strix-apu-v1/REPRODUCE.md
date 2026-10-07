# Reproducing `qwen3.8-flash-next-iq4xs--halogen-strix-apu-v1`

Everything needed to run this build. `build.yaml` has the rationale and (once run)
the measured results; this file is the mechanical recipe.

## Image

Public, pre-built - no Dockerfile or build step in this repo.

```sh
docker pull ghcr.io/peonist-ai/halogen-flash-server:0.16.4
```

Engine: https://github.com/peonist-ai/halogen-flash-server

## Weights

Bring-your-own-GGUF: reuses the exact same files as every other flash-next
build in this repo, already on disk if any of them has run:

```sh
/var/lib/ai-models/qwen3.8-flash-next-iq4xs/UD-IQ4_XS/*.gguf
```

Plus two small sidecar files in peonist-ai's own `.hgn` format (vision tower,
MTP draft head) that the container downloads itself on first boot via
`HALOGEN_DOWNLOAD`, into `/var/lib/ai-models/halogen-flash-next-sidecars`
(created once, empty, read-write-mounted - not tracked by this repo's usual
`.download-complete` convention, since halogen manages this itself).

## Running it

```sh
modelctl up --exclusive qwen3.8-flash-next-iq4xs--halogen-strix-apu-v1
```

Port `8208`. First boot downloads the ~2.3 GiB of sidecar files and repacks the
GGUF tensors into halogen's internal layout (documented as ~18s cold, ~9s warm
if `HALOGEN_GGUF_CACHE=1` is set later) - expect a real one-time delay beyond
the usual health-check wait.

## Why this exists

See `build.yaml` for the full rationale - in short, every llama.cpp-family
engine trialed in M-160 shares flash-next's real ~111.6 GiB footprint on this
hardware; halogen's own docs claim a dramatically smaller one for the same
model/quant, which (if true on this box) changes the whole memory-margin
picture this session has been fighting.

## What's NOT yet validated here

Everything - this is the mechanical recipe for a build that hasn't booted yet
as of being written. No correctness check, no real memory numbers on this box,
no benchmark, no crash-repro run.
