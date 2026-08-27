#!/usr/bin/env bash
# 2026-08-22: build ggml-org/llama.cpp PR #27342 (DFlash2 support) with
# Vulkan/RADV as `strix-halo-r9700-llm-builds/llamacpp-dflash2:vulkan-radv`. Run on the
# box. Mirrors scripts/build-laguna-fork.sh's structure exactly (same base
# image, same build-then-verify shape) - see the dockerfile's own header
# comment for why this is a separate image, not a laguna-fork variant.
set -euo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

docker build \
  -f docker/llamacpp-dflash2-vulkan-radv.dockerfile \
  -t strix-halo-r9700-llm-builds/llamacpp-dflash2:vulkan-radv \
  docker/

echo "BUILD_OK"
docker run --rm strix-halo-r9700-llm-builds/llamacpp-dflash2:vulkan-radv \
  sh -c 'echo "pr_commit=$(cat /build/fork-commit.txt)" && /build/build/bin/llama-cli --version'
