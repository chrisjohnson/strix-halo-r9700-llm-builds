#!/usr/bin/env bash
# M-139: build JeremiahM37/strix-halo-sglang (vendored, gfx1151) as
# `strix-halo-r9700-llm-builds/strix-halo-sglang:gfx1151`. Run on the box.
set -euo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

docker build \
  -f docker/strix-halo-sglang.dockerfile \
  -t strix-halo-r9700-llm-builds/strix-halo-sglang:gfx1151 \
  docker/

echo "BUILD_OK"
# `import sglang` eagerly touches the GPU via aiter/Triton driver init, so
# unlike a plain --version check this smoke test needs real device access -
# without it, Triton's driver probe fails with "0 active drivers", not a
# build problem.
docker run --rm \
  --device /dev/kfd --device /dev/dri \
  --group-add video --group-add render \
  --security-opt seccomp=unconfined \
  strix-halo-r9700-llm-builds/strix-halo-sglang:gfx1151 \
  python3 -c "import sglang; print('sglang import OK')"
