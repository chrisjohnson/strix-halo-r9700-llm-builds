# Build + run container for poolsideai/llama.cpp branch `laguna` with Vulkan/RADV
# (M-053: the one untried speculative-decoding candidate — real DFlash on Vulkan).
#
# The kyuz0 Strix Halo toolbox image already ships the complete runtime (Mesa RADV
# Vulkan driver) AND the dev toolchain (cmake, gcc, ninja, glslc, vulkan headers),
# so one stage serves as both builder and runtime. The built binaries land in
# /build/build/bin and the fork commit is recorded in /build/fork-commit.txt.
FROM docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv

# The toolbox image has gcc/glslc but no usable linker: binutils is present yet
# /usr/bin/ld -> /etc/alternatives/ld is a dangling symlink (the image's
# alternatives database is broken), so CMake's compiler-probe fails with
# `collect2: fatal error: cannot find 'ld'`. Repair the link to the real ld.bfd.
RUN dnf install -y binutils && dnf clean all \
    && ln -sf /usr/bin/ld.bfd /usr/bin/ld

WORKDIR /build
RUN git clone --depth 1 --branch laguna https://github.com/poolsideai/llama.cpp.git /build/src \
    && git -C /build/src rev-parse HEAD > /build/fork-commit.txt

WORKDIR /build/src
# GCC 15 header-hygiene fix: common/speculative.cpp uses std::isfinite (the DFlash
# row-clamping path) without including <cmath>; older libstdc++ provided it
# transitively, GCC 15 does not. Surgical one-line include — the only <cmath>-missing
# user in the compiled (non-SYCL, non-test) tree.
RUN sed -i '/#include <map>/a #include <cmath>' /build/src/common/speculative.cpp \
    && grep -n "include <cmath>" /build/src/common/speculative.cpp
RUN cmake -B /build/build -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF \
    && grep -E "GGML_VULKAN|LLAMA_VULKAN" /build/build/CMakeCache.txt \
    && cmake --build /build/build -j --target llama-server llama-bench llama-cli

WORKDIR /build
