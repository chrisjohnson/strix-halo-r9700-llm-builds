#!/usr/bin/env bash
# M-086: build poolsideai/llama.cpp branch `laguna` with ROCm/HIP (gfx1151) as
# `strix-halo-r9700-llm-builds/llamacpp-laguna-fork:rocm-7.2.2`. Run on the box.
# ROCm retry — NEW image (not a rebuild of M-055's rocm-7.14), with the
# chip-specific build flags + ROCm version M-055's build was missing. See
# docker/llamacpp-laguna-fork-rocm-7.2.2.dockerfile for the full rationale.
set -euo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

docker build \
  -f docker/llamacpp-laguna-fork-rocm-7.2.2.dockerfile \
  -t strix-halo-r9700-llm-builds/llamacpp-laguna-fork:rocm-7.2.2 \
  docker/

echo "BUILD_OK"
docker run --rm strix-halo-r9700-llm-builds/llamacpp-laguna-fork:rocm-7.2.2 \
  sh -c 'echo "fork_commit=$(cat /build/fork-commit.txt)" && /build/build/bin/llama-cli --version'
