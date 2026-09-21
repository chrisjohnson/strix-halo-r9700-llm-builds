#!/usr/bin/env bash
# M-149, 2026-09-20: build leejet/stable-diffusion.cpp with Vulkan/RADV
# (gfx1151) as `strix-halo-r9700-llm-builds/sdcpp:vulkan-radv`. Run on the
# box. Mirrors scripts/build-laguna-fork.sh's structure exactly (same base
# image, same build-then-verify shape).
set -euo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

docker build \
  -f docker/sdcpp-vulkan-radv.dockerfile \
  -t strix-halo-r9700-llm-builds/sdcpp:vulkan-radv \
  docker/

echo "BUILD_OK"
docker run --rm strix-halo-r9700-llm-builds/sdcpp:vulkan-radv \
  sh -c 'echo "sdcpp_commit=$(cat /build/fork-commit.txt)" && /build/build/bin/sd-server --help | head -5'
