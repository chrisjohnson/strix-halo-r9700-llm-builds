#!/usr/bin/env bash
# Clone/pin codeberg.org/ggz14/radiance-vllm-mxfp4 at an exact commit, build the
# loadable MXFP4 checkpoint from AMD's release (one-time, idempotent), and serve
# Qwen3.8-27B in native MXFP4 (W4A8) on a single gfx1201 GPU via the upstream
# repo's own serve-mxfp4.sh launcher.
#
# This intentionally does not vendor the upstream repo's source into this
# repo: it is a third-party fork with its own patch files, HIP kernels and
# launcher scripts that this repo does not own or maintain. What IS owned
# here is the pinned commit, the exact invocation, and the checkpoint paths -
# this script is what actually runs on the box, not freehand SSH commands
# against a manual clone.
#
# Run on the box (NixOS has no /bin/bash, so: bash scripts/run-radiance-mxfp4.sh).
#
# Usage:
#   scripts/run-radiance-mxfp4.sh setup    clone/checkout the pinned commit,
#                                          build the MXFP4+fp8-MTP checkpoint
#                                          if it doesn't exist yet
#   scripts/run-radiance-mxfp4.sh serve    run setup if needed, then exec the
#                                          upstream serve-mxfp4.sh launcher
#                                          (foreground; Ctrl-C stops it)
#
# Checkpoints are expected to already exist under /var/lib/ai-models, put
# there by local-ai-machine's declarative model-download services:
#   /var/lib/ai-models/qwen3.8-27b-quark-awq-mxfp4   (AMD's raw release)
#   /var/lib/ai-models/qwen3.8-27b-dflash2-fp8       (optional FP8 drafter)
# The checkpoint this actually serves (source + fp8-requantized MTP head) is
# written to /var/lib/ai-models/qwen3.8-27b-mxfp4-mtpfp8 - a locally derived
# artifact, not itself declaratively downloaded, same pattern as this repo's
# other locally-quantized derivatives.
set -euo pipefail

RADIANCE_REPO=${RADIANCE_REPO:-https://codeberg.org/ggz14/radiance-vllm-mxfp4}
# Pin to an exact commit so a later upstream push (single-maintainer,
# actively-changing repo) can never silently change what this serves.
RADIANCE_COMMIT=${RADIANCE_COMMIT:-505513660a4f74016aba432a8393ad368dfc825f}
CHECKOUT=${RADIANCE_CHECKOUT:-/home/chris/radiance-vllm-mxfp4}

MODELS=/var/lib/ai-models
SRC=$MODELS/qwen3.8-27b-quark-awq-mxfp4
SNAP=$MODELS/qwen3.8-27b-mxfp4-mtpfp8
DRAFTER=$MODELS/qwen3.8-27b-dflash2-fp8

MODE=${1:-serve}
case "$MODE" in
  setup|serve) ;;
  *) echo "usage: $0 [setup|serve]" >&2; exit 2 ;;
esac

step() { echo; echo "=== $* ==="; }

step "pinned checkout: $RADIANCE_COMMIT"
if [ ! -d "$CHECKOUT/.git" ]; then
  git clone "$RADIANCE_REPO" "$CHECKOUT"
fi
git -C "$CHECKOUT" fetch origin
git -C "$CHECKOUT" checkout --detach "$RADIANCE_COMMIT"
GOT=$(git -C "$CHECKOUT" rev-parse HEAD)
[ "$GOT" = "$RADIANCE_COMMIT" ] || { echo "checkout landed on $GOT, expected $RADIANCE_COMMIT" >&2; exit 1; }

step "source checkpoint"
[ -f "$SRC/config.json" ] || { echo "missing $SRC/config.json - wait for download-model-qwen3.8-27b-quark-awq-mxfp4.service to finish" >&2; exit 1; }

step "loadable checkpoint (fp8 MTP head rewrite)"
if [ -f "$SNAP/config.json" ]; then
  echo "already built at $SNAP"
else
  echo "requantizing the MTP head to fp8 (~15 min, one file rewritten) - not optional,"
  echo "see fp8_mtp.py's own header for why AMD's release does not load as-is"
  python3 "$CHECKOUT/fp8_mtp.py" "$SRC" "$SNAP" || {
    docker run --rm \
      -v "$SRC":"/src":ro \
      -v "$MODELS":/models \
      -v "$CHECKOUT":/repo:ro \
      --entrypoint python3 stilldeadcode/vllm-radiance:0.9.3 \
      /repo/fp8_mtp.py /src "/models/$(basename "$SNAP")"
  }
  [ -f "$SNAP/config.json" ] || { echo "fp8_mtp.py did not produce $SNAP/config.json" >&2; exit 1; }
fi

[ "$MODE" = setup ] && { echo; echo "setup complete"; exit 0; }

step "serve"
if [ -f "$DRAFTER/config.json" ]; then
  SPEC_METHOD_DEFAULT=dflash
else
  echo "no drafter at $DRAFTER - serving without dflash speculative decoding (SPEC_METHOD=mtp)"
  SPEC_METHOD_DEFAULT=mtp
fi

cd "$CHECKOUT"
exec env \
  MODELS="$MODELS" \
  SNAP="$SNAP" \
  DRAFTER="$DRAFTER" \
  SPEC_METHOD="${SPEC_METHOD:-$SPEC_METHOD_DEFAULT}" \
  RUNTIME=docker \
  NAME="${NAME:-radiance-mxfp4-r9700}" \
  PORT="${PORT:-8012}" \
  bash serve-mxfp4.sh "${@:2}"
