#!/usr/bin/env bash
# M-055: build poolsideai/llama.cpp branch `laguna` with ROCm/HIP (gfx1151) as
# `strix-halo-r9700-llm-builds/llamacpp-laguna-fork:rocm-7.14`. Run on the box.
# Control build for the DFlash acceptance question — community numbers are from
# a ROCm/HIP build; this reproduces their config on our hardware.
set -euo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

docker build \
  -f docker/llamacpp-laguna-fork-rocm.dockerfile \
  -t strix-halo-r9700-llm-builds/llamacpp-laguna-fork:rocm-7.14 \
  docker/

echo "BUILD_OK"
docker run --rm strix-halo-r9700-llm-builds/llamacpp-laguna-fork:rocm-7.14 \
  sh -c 'echo "fork_commit=$(cat /build/fork-commit.txt)" && /build/build/bin/llama-cli --version'
