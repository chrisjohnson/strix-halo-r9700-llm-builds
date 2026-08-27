# Build + run container for ggml-org/llama.cpp PR #27342 ("spec: add DFlash2
# support (local convolution + candidate selector)") with Vulkan/RADV
# (gfx1035/gfx1201, the R9700's Vulkan device) - 2026-08-22, DFlash2 for
# qwen3.8-27b. NOT the same as llamacpp-laguna-fork-vulkan-radv.dockerfile:
# that's poolside's separate PRIVATE fork (branch `laguna`) implementing the
# ORIGINAL DFlash. This is upstream ggml-org/llama.cpp, still on an UNMERGED
# PR against mainline master, implementing a genuinely different, newer
# technique (DFlash 2). Confirmed live (2026-08-22) that the stock
# kyuz0/amd-strix-halo-toolboxes:vulkan-radv image cannot load a DFlash2
# draft GGUF at all ("wrong number of tensors; expected 81, got 58") - this
# custom build is what that failure requires.
#
# Same base image as the laguna fork build (already ships the Mesa RADV
# Vulkan driver + full dev toolchain: cmake, gcc, ninja, glslc, vulkan
# headers), for the same one-stage-serves-as-builder-and-runtime reason.
FROM docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv

# Same broken-alternatives-database repair the laguna fork build needed
# (/usr/bin/ld -> /etc/alternatives/ld is a dangling symlink in this image) -
# applying proactively since it's an image-level issue, not branch-specific.
RUN dnf install -y binutils && dnf clean all \
    && ln -sf /usr/bin/ld.bfd /usr/bin/ld

WORKDIR /build
# Unmerged PR: clone mainline, then fetch+checkout the PR's head ref
# directly from GitHub's pull/<n>/head convention (no named branch exists
# on the upstream repo itself, unlike poolside's laguna fork).
RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /build/src \
    && cd /build/src \
    && git fetch --depth 1 origin pull/27342/head:pr-27342 \
    && git switch pr-27342 \
    && git rev-parse HEAD > /build/fork-commit.txt

WORKDIR /build/src
# The laguna fork build needed a one-line <cmath> include fix for GCC 15
# header hygiene (common/speculative.cpp's std::isfinite use). This PR also
# touches common/speculative.cpp (220 changed lines per its GitHub diff), so
# the same class of failure is plausible but not assumed - only applied if
# the plain build actually fails with the same missing-<cmath> error.
RUN cmake -B /build/build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF \
    && grep -E "GGML_VULKAN|LLAMA_VULKAN" /build/build/CMakeCache.txt \
    && cmake --build /build/build -j --target llama-server llama-bench llama-cli

WORKDIR /build
