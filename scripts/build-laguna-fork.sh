#!/usr/bin/env bash
# M-053: build poolsideai/llama.cpp branch `laguna` with Vulkan/RADV (gfx1151) as
# `strix-halo-r9700-llm-builds/llamacpp-laguna-fork:vulkan-radv`. Run on the box.
set -euo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

docker build \
  -f docker/llamacpp-laguna-fork-vulkan-radv.dockerfile \
  -t strix-halo-r9700-llm-builds/llamacpp-laguna-fork:vulkan-radv \
  docker/

echo "BUILD_OK"
docker run --rm strix-halo-r9700-llm-builds/llamacpp-laguna-fork:vulkan-radv \
  sh -c 'echo "fork_commit=$(cat /build/fork-commit.txt)" && /build/build/bin/llama-cli --version'
