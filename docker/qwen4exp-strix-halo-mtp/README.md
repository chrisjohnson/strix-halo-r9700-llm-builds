# qwen4exp / EngramHalo image builds

Everything needed to rebuild the images that `builds/qwen3.8-flash-next-iq4xs--*` reference.
The model weights are not here (they live under `/var/lib/ai-models/` on the box); these are
the engine images.

This directory is the build context for all three — the Dockerfiles `COPY` their patches from
here, so build from inside this directory, not from the repo root.

| Dockerfile | Image tag | Used by |
|---|---|---|
| `Dockerfile.rocm-7.14` | `strix-halo-r9700-llm-builds/qwen4exp-strix-halo-mtp:rocm-7.14` | `...-strixhalo-mtp-v1`, `-v2`, `-v3` |
| `Dockerfile.rocm-7.14-lazy-direct` | `...:rocm-7.14-lazy-direct` | `...-rocm714-lazy-direct-strixhalo-mtp-v1` |

```sh
cd docker/qwen4exp-strix-halo-mtp
docker build -f Dockerfile.rocm-7.14            -t strix-halo-r9700-llm-builds/qwen4exp-strix-halo-mtp:rocm-7.14            .
docker build -f Dockerfile.rocm-7.14-lazy-direct -t strix-halo-r9700-llm-builds/qwen4exp-strix-halo-mtp:rocm-7.14-lazy-direct .
```

These images are **built locally on the box**, not by CI — unlike the `llm-inference-bench`
image, which `.github/workflows/build.yml` builds and pushes. Nothing here is in a registry.

## Provenance

Upstream source is third-party: `github.com/Aristo94/EngramHalo.cpp`, branch
`strix-halo-qwen4exp`, chosen (and explicitly confirmed by Chris) because it is the only
branch found with a working MTP draft head for Qwen3.8-Flash-Next on Strix Halo. The
reasoning, alternatives, and the patch review are in the header of `Dockerfile.rocm-7.14`.

**The original `Dockerfile.rocm-7.14` does not pin a commit** — it clones the branch head, so
it is not reproducible if that branch moves. `Dockerfile.rocm-7.14-lazy-direct` does pin one
(`ARG COMMIT=`), added 2026-09-27. Pinning the original as well is a reasonable follow-up but
was left alone because it is referenced by three already-recorded builds.

## The patches

| Patch | Applied by | What it is |
|---|---|---|
| `llama-cpp-25992-rocm-host-buffer.patch` | both | ROCm host-buffer workaround for upstream #25992 (open PR #25863). Correctness fix for multi-slot serving on integrated GPUs. |
| `llama-cpp-qwen38-per-buffer-mmap.patch` | `Dockerfile.rocm-7.14` only | Per-buffer mmap / async uploads, used in the measured builds. Applied conditionally — skipped if it no longer fits. |
| `llama-cpp-29030-lazy-direct.patch` | `Dockerfile.rocm-7.14-lazy-direct` only | Upstream PR #29030, **still open**. Replaces the lazy-tensor gather with direct reads. Worth +21.9-29.1% prefill; see the build's `build.yaml`. |

**The last two are mutually exclusive.** Both rewrite `src/llama-model-loader.{cpp,h}`, and
`llama-cpp-qwen38-per-buffer-mmap.patch` neither applies nor reverses on top of #29030. That
is why `Dockerfile.rocm-7.14-lazy-direct` relies on the per-buffer patch's own conditional
and ends up without it — which is the documented fallback, and the one caveat on any A/B
between the lazy-direct build and v1/v2/v3.

## Flag rename, easy to get wrong

PR #29030 replaces `--tensor-read-lazy` with `--lazy-mode`, and `on` now means **direct
reads** rather than mmap demand-faulting. There is no `on-direct` value — `on` is it. A
container on the `:rocm-7.14-lazy-direct` image passing `--tensor-read-lazy on` **will not
start**.
