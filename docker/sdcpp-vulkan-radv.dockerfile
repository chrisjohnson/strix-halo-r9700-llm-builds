# Build + run container for leejet/stable-diffusion.cpp with Vulkan/RADV
# (M-149, 2026-09-20: first image-generation build in this catalog, for
# Qwen-Image-2.1). llama.cpp cannot serve this model class at all -
# llama-server has no image-output endpoint, and llama.cpp fails to load
# the `qwen_image` architecture outright - so this is a different engine,
# not a config variant of an existing build.
#
# Same base image and same-stage builder-and-runtime shape as the Laguna/
# DFlash2 Vulkan builds: the kyuz0 Strix Halo toolbox image already ships
# the Mesa RADV Vulkan driver plus the full dev toolchain (cmake, gcc,
# ninja, glslc, vulkan headers) this needs, and Vulkan needs no gfx-target
# build flag (unlike the HIP/ROCm backend, which would need
# GPU_TARGETS=gfx1151) - the same reason Vulkan/RADV is this catalog's
# already-proven path on this exact APU for every other Strix build.
FROM docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv

# Same broken-alternatives-database repair every other custom build here
# needs (/usr/bin/ld -> /etc/alternatives/ld is a dangling symlink in this
# image).
RUN dnf install -y binutils && dnf clean all \
    && ln -sf /usr/bin/ld.bfd /usr/bin/ld

WORKDIR /build
# stable-diffusion.cpp vendors ggml as a submodule - --recurse-submodules
# is required, unlike the llama.cpp builds above which vendor nothing.
RUN git clone --depth 1 --recurse-submodules --shallow-submodules \
      https://github.com/leejet/stable-diffusion.cpp.git /build/src \
    && git -C /build/src rev-parse HEAD > /build/fork-commit.txt

WORKDIR /build/src
RUN cmake -B /build/build -DSD_VULKAN=ON -DCMAKE_BUILD_TYPE=Release \
    && grep -E "SD_VULKAN" /build/build/CMakeCache.txt \
    && cmake --build /build/build -j --target sd-cli sd-server

WORKDIR /build
