# DS4 (DeepSeek V4 Flash) dual-GPU build: R9700 eGPU + Strix Halo APU, via
# Luce-Org/lucebox-hub's dflash_server. M-137: this is the fix build, not
# upstream stock - upstream ROCm 6.4.1 crashes deterministically during
# dual-GPU MoE weight loading (see
# https://github.com/Luce-Org/lucebox/issues/681), and stock dflash_server
# has a separate heap-use-after-free in its decode-path worker pool that
# crashes within 1-30 requests under real dual-GPU load (see
# https://github.com/Luce-Org/lucebox/issues/682). Both are fixed here:
#   1. ROCm 7.2.2 (see issue #681's confirmed fix).
#   2. Source cloned from a personal fork carrying the pool-fix commits
#      (233c8b8..176c0ae on top of upstream f0c5a5d) rather than upstream
#      directly - see issue #682 for the full patch and root-cause writeup.
# Neither fix is merged upstream; this Dockerfile exists so the fix is
# buildable from a real, pinned git ref instead of only living as a
# throwaway container on one box (M-137's original test build).
#
# Base: rocm/dev-ubuntu-24.04:7.2.2-complete directly (AMD's own official
# image), NOT ghcr.io/luce-org/lucebox-hub:rocm with an in-place ROCm
# upgrade - that was tried first and abandoned after five separate
# dpkg-conflict failures (see M-137's decision log for the full trail):
# lucebox-hub's own base image ships ROCm 6.4.1's unversioned packages
# baked in, and no combination of --force-overwrite / split apt-get calls
# / explicit purge-then-install reliably coexists with the versioned
# 7.2.2 packages (apt's own dependency resolver keeps pulling in stray
# unversioned packages like `roctracer` even after purging the ones it
# was expected to need). Starting from AMD's clean 7.2.2 image instead -
# the same base every other custom-fork build in this repo already uses,
# e.g. docker/llamacpp-laguna-fork-rocm-7.2.2.dockerfile - sidesteps the
# conflict entirely: there's nothing old to collide with. dflash_server
# is a self-contained compiled binary (no Python/uv runtime dependency on
# lucebox-hub's own image at runtime), so nothing needs to be copied over
# from the original ghcr.io image either.
FROM rocm/dev-ubuntu-24.04:7.2.2-complete

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
        build-essential cmake ninja-build git rocwmma-dev hipcub-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --branch m137-ds4-matvec-pool-uaf-fix --depth 1 --recurse-submodules --shallow-submodules \
      https://github.com/chrisjohnson/lucebox.git /build/src \
    && git -C /build/src rev-parse HEAD > /build/fork-commit.txt

WORKDIR /build/src/server
RUN cmake -S . -B build \
        -DDFLASH27B_GPU_BACKEND=hip \
        -DDFLASH27B_HIP_ARCHITECTURES='gfx1151;gfx1201' \
        -DGGML_HIP_GRAPHS=ON \
        -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j 32 --target dflash_server

# ROCm's versioned lib dirs can live outside the loader's default search
# paths - same fix as the laguna-fork rocm-7.2.2 build.
RUN find /opt/rocm -maxdepth 5 -type d \( -name lib -o -name lib64 \) \
    | sort >> /etc/ld.so.conf.d/rocm.conf \
    && ldconfig

WORKDIR /build/src/server/build
