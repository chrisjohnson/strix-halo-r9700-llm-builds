# Build + run container for poolsideai/llama.cpp branch `laguna` with ROCm/HIP
# targeting gfx1151 (Strix Halo). M-086: ROCm RETRY — a fresh image, NOT a
# rebuild of M-055's rocm-7.14 image (that build never got DFlash serving; the
# card's whole thesis is that the M-055 Dockerfile was missing chip-specific
# fixes, not that ROCm itself is broken on this hardware — see M-086's
# Decision log for the two community sources this is based on).
#
# Differences from M-055's docker/llamacpp-laguna-fork-rocm.dockerfile:
#   - ROCm 7.2.2 base (community-validated "known-good" range for gfx1151 is
#     7.2.0-7.2.3; M-055 used 7.14, outside that range and untested by either
#     guide). 7.x as a family also has a documented throughput regression vs
#     6.4.4 — see docker/llamacpp-laguna-fork-rocm-6.4.4.dockerfile for that
#     comparison build.
#   - GGML_HIP_ROCWMMA_FATTN=ON + rocwmma-dev package: M-055 ran with -fa 0
#     assuming flash attention was fundamentally broken on gfx1151/ROCm; per
#     the community docs this is actually a missing-package problem.
#   - GGML_HIP_NO_VMM=ON: documented "critical stability fix" for gfx1151.
#   - GGML_HIP_MMQ_MFMA=ON: additional gfx1151-specific correctness/perf flag.
# Sources: ggml-org/llama.cpp discussion #20856 ("Known-Good Strix Halo ROCm +
# llama.cpp Stack"), LucRoot/Strix-Halo-Linux-Llama_cpp-ROCm.
#
# Base: rocm/dev-ubuntu-24.04:7.2.2-complete (the closest analog to the old
# 7.14.0-full tag in this repo's newer versioned line — carries the
# version-matched HIP SDK: hipcc, hipblas-devel, rocblas-devel, rocwmma-dev
# available via apt).
#
# The poolside fork is pinned to the EXACT commit used by both the Vulkan
# build and M-055's ROCm control (04b2b72cb54048ead292884adbe11f284e3ec950) so
# any acceptance/throughput differences are attributable to backend/build
# flags, not code drift. Binaries land in /build/build/bin and the fork commit
# in /build/fork-commit.txt, matching the Vulkan build's layout so
# scripts/benchmark-laguna-dflash.sh works unchanged (IMAGE + FA_FLAG env
# overrides).
FROM rocm/dev-ubuntu-24.04:7.2.2-complete

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build git rocwmma-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch laguna https://github.com/poolsideai/llama.cpp.git /build/src \
    && git -C /build/src fetch --depth 1 origin 04b2b72cb54048ead292884adbe11f284e3ec950 \
    && git -C /build/src checkout --detach FETCH_HEAD \
    && git -C /build/src rev-parse HEAD > /build/fork-commit.txt

WORKDIR /build/src
# Same GCC <cmath> guard as the Vulkan/M-055 ROCm builds (harmless no-op if
# already available transitively on this toolchain).
RUN grep -q '#include <cmath>' common/speculative.cpp \
    || sed -i '/#include <map>/a #include <cmath>' common/speculative.cpp
RUN cmake -B /build/build \
        -DGGML_HIP=ON -DGGML_VULKAN=OFF \
        -DAMDGPU_TARGETS=gfx1151 \
        -DGGML_HIP_ROCWMMA_FATTN=ON \
        -DGGML_HIP_NO_VMM=ON \
        -DGGML_HIP_MMQ_MFMA=ON \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CURL=OFF \
    && grep -E "GGML_HIP|AMDGPU_TARGETS" /build/build/CMakeCache.txt \
    && cmake --build /build/build -j6 --target llama-server llama-bench llama-cli llama-quantize

# ROCm's versioned lib dirs (e.g. /opt/rocm/core-<ver>/lib) can live outside the
# loader's default search paths, so freshly-linked binaries fail at runtime
# with "cannot open shared object file: libhipblas.so.3" without this — same
# fix as M-055's rocm-7.14 image, kept defensively even if 7.2.2's layout
# turns out to already be on the default path.
RUN find /opt/rocm -maxdepth 5 -type d \( -name lib -o -name lib64 \) \
    | sort >> /etc/ld.so.conf.d/rocm.conf \
    && ldconfig

WORKDIR /build
