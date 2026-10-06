# ds4 (antirez/ds4, "DwarfStar") — Qwen3.8-Flash-Next integration branch

A from-scratch (not llama.cpp-derived) C inference engine, trialed as an
alternative engine for Qwen3.8-Flash-Next (M-16x research trial, Chris:
"I'm definitely ok with the ds4 unmerged PRs as well. I don't mind trying
out new builds.").

## What this is

`Dockerfile.rocm-10.0-qwen4next` is kyuz0/strix-halo-ds4-toolbox's own
`toolboxes/Dockerfile.rocm-10.0` (the proven, working ROCm/gfx1151 ds4
build recipe used by this repo's other `ds4-*` builds), retargeted at the
draft Qwen3.8-Flash-Next support in
[antirez/ds4#1070](https://github.com/antirez/ds4/pull/1070) (draft; actual
head branch is `kyuz0/ds4@codex/qwen38-main-integration-20260917` — the PR's
own description says it already includes its prerequisite changes from
PR #1036, so that doesn't need a separate merge).

Everything else — ROCm 10.0 packages, the `make strix-halo ROCM_ARCH=gfx1151`
build command, the runtime stage — is unchanged from the toolbox recipe. The
only two differences from the upstream Dockerfile:

- `ARG BRANCH` defaults to `codex/qwen38-main-integration-20260917` instead
  of `main-gfx1151`, and the build pins an explicit `ARG ENGINE_COMMIT` sha
  (this repo's reproducibility convention — see every other build's
  Dockerfile for the same pattern).
- The three feature patches the toolbox applies (PR #2, #1012, #1165 —
  unrelated opt-in features, not core ROCm enablement) are now best-effort:
  `git am` is tried, and a failure is tolerated (`git am --abort || true`)
  rather than failing the build. They may not apply cleanly against this
  different branch; they are not required for a basic working build.

## Building it

```sh
cd docker/kyuz0-ds4-strix-halo
docker build -f Dockerfile.rocm-10.0-qwen4next \
  --build-arg ENGINE_COMMIT="$(gh api repos/kyuz0/ds4/commits/codex/qwen38-main-integration-20260917 --jq .sha)" \
  -t strix-halo-r9700-llm-builds/kyuz0-ds4-strix-halo:rocm-10.0-qwen4next .
```

(`ENGINE_COMMIT` already defaults to the sha captured when this Dockerfile
was written; pass `--build-arg` only to pick up a newer commit on the
branch.)

## Model

`qwen38-q4k` from this branch's `download_model.sh` — one 165.11 GiB GGUF
(69.74 GiB resident weights, MXFP4/Q4_K experts, BF16 n-grams kept on disk),
from HF repo `antirez/qwen3.8-flash-next-gguf`, file
`Qwen3.8-Flash-Next-Q4.gguf`. Vision projector is `qwen38-vision`
(`mmproj-Qwen3.8-Flash-Next-Q8_0.gguf`, ~0.6 GiB, from
`ggml-org/Qwen3.8-Flash-Next-GGUF`). Chosen over the smaller `qwen38-q2`
target to stay a closer quality match to production's IQ4_XS quant for a
fair speed comparison.

## API

`ds4-server` has its own native HTTP API — see
[docs/SERVER.md](https://github.com/kyuz0/ds4/blob/codex/qwen38-main-integration-20260917/docs/SERVER.md)
on this branch. It exposes `POST /v1/chat/completions` (OpenAI-style),
`POST /v1/responses`, `POST /v1/completions`, and `POST /v1/messages`
(Anthropic-style) — so an OpenAI-compatible client should work directly
against `/v1/chat/completions` without an adapter.

See the build directory's own `build.yaml` for measured results.
