# Build + run container for poolsideai/llama.cpp branch `laguna` with ROCm/HIP
# targeting gfx1151 (Strix Halo). M-055: ROCm control build for the DFlash
# acceptance question — the community measured 73.5-90.6% draft acceptance on
# a ROCm/HIP build of this exact fork; our Vulkan build (M-053) only gets
# 10-19%. This image reproduces the community's config so we can measure
# acceptance on THIS box and decide whether the collapse is Vulkan-specific.
#
# Base: the official AMD rocm dev image at the same ROCm release as the box's
# existing `kyuz0/strix-halo-ds4-toolbox:rocm-7.14` runtime (7.14.0-full). The
# dev image carries a complete, version-matched HIP SDK (hipcc, hipblas-devel,
# rocblas-devel) so there is no runtime/dev version-mixing.
#
# The poolside fork is pinned to the EXACT commit of the Vulkan build
# (04b2b72cb54048ead292884adbe11f284e3ec950) so acceptance differences are
# attributable to backend, not code drift. Binaries land in /build/build/bin
# and the fork commit in /build/fork-commit.txt, matching the Vulkan build's
# layout so scripts/benchmark-laguna-dflash.sh works unchanged (IMAGE + FA_FLAG
# env overrides).
FROM rocm/dev-ubuntu-24.04:7.14.0-full

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch laguna https://github.com/poolsideai/llama.cpp.git /build/src \
    && git -C /build/src fetch --depth 1 origin 04b2b72cb54048ead292884adbe11f284e3ec950 \
    && git -C /build/src checkout --detach FETCH_HEAD \
    && git -C /build/src rev-parse HEAD > /build/fork-commit.txt

WORKDIR /build/src
# Same GCC-15 <cmath> guard as the Vulkan build (harmless no-op on this
# toolchain if already available transitively).
RUN grep -q '#include <cmath>' common/speculative.cpp \
    || sed -i '/#include <map>/a #include <cmath>' common/speculative.cpp
RUN cmake -B /build/build \
        -DGGML_HIP=ON -DGGML_VULKAN=OFF \
        -DAMDGPU_TARGETS=gfx1151 \
        -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CURL=OFF \
    && grep -E "GGML_HIP|AMDGPU_TARGETS" /build/build/CMakeCache.txt \
    && cmake --build /build/build -j6 --target llama-server llama-bench llama-cli

# ROCm 7.14 keeps its libraries under /opt/rocm/core-7.14/lib (NOT the loader's
# default paths), so the freshly-linked binaries cannot find hipblas/rocblas at
# runtime. Register every ROCm lib dir with ldconfig and bake the cache into the
# image; without this, llama-cli/server fail with "cannot open shared object
# file: libhipblas.so.3".
RUN find /opt/rocm -maxdepth 5 -type d \( -name lib -o -name lib64 \) \
    | sort >> /etc/ld.so.conf.d/rocm.conf \
    && ldconfig

WORKDIR /build
