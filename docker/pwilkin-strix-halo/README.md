# pwilkin's Strix Halo stack (ROCm 10.0 runtime + strix-halo llama.cpp)

Reproduces the stack behind the "1.2k t/s prefill on Strix Halo" result
(https://pwilkin.github.io/strix-halo/journey.html), as a container.

## What it is, in their words

- **Runtime**: a change to the ROCm *userspace* runtimes, not to any inference engine —
  "Retained PM4 command lists for HIP graphs". A HIP graph materialises its PM4 packets once
  and replays the retained list, instead of re-encoding per node per launch. Five commits on
  `pwilkin/rocm-systems@ilintar-experiments`. Enabled by an env var, experimental.
- **Engine**: 16+ commits on `pwilkin/llama.cpp@strix-halo`, each measured separately.
  The largest single step is `964c6f2f0` "tiled gated delta-net for large prefill batches"
  (2.37x). Others: bf16 WMMA dequant GEMM (1.42x isolated), maskless KQ path (1.48x),
  fused HC gate GEMM (1.19x). Their sparse-attention path measured break-even and is gated.

## Pinned revisions (from their install.sh, not guessed)

| Component | Repo | Branch | Commit |
|---|---|---|---|
| ROCm runtime | `pwilkin/rocm-systems` | `ilintar-experiments` | `7dda3ac6cfe6bbe0b7f08c23a67cfa118d8641a1` |
| llama.cpp | `pwilkin/llama.cpp` | `strix-halo` | `b0f31f5876ef3856b55f5bb88072cc96e5effafe` |

## The launch config their installer writes

```
-dev ROCm0 -ngl 999 -fa on -fit off
--load-mode none            # no mmap at all
--lazy-mode on-direct       # rows are pread() on demand, from a thread pool
-ctk f16 -ctv f16
-c ${CTX_SIZE:-65536} -b ${BATCH_SIZE:-16384} -ub ${UBATCH_SIZE:-16384}
--parallel ${PARALLEL:-1} --jinja
--spec-type draft-mtp --spec-draft-model <shared MTP Q8_0> --spec-draft-ngl 99
--spec-draft-n-max ${MTP_N_MAX:-3}
```

with runtime env `HSA_OVERRIDE_GFX_VERSION=11.5.1`,
`GGML_HIP_ENABLE_UNIFIED_MEMORY=1`, `ENABLE_RETAINED_PM4=1` (and `DEBUG_HIP_GRAPH_PM4=1`).

`--load-mode none` plus `--lazy-mode on-direct` is, per their comment, "what keeps the 27.5 GB
per-layer-embedding table out of the resident set".

## Caveats carried over from their own notes

- HIP graphs do **not** engage for prefill — each chunk shape occurs once per request, and
  capture needs two consecutive graphs with unchanged properties. Retained PM4 pays off in
  **decode**, not prefill. Their page says so explicitly.
- Decode is "still behind where it should be".
- Their model is `IQ4_NL` (110 GiB, 9 shards) plus a **shared-embedding** MTP draft — not our
  `UD-IQ4_XS`. Engine-vs-engine comparison must use the same weights; see the build entry.

## Building it (docker, not podman)

```sh
cd docker/pwilkin-strix-halo
docker build -f Dockerfile.rocm-10.0-strix-llama \
  -t strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct .
```

40-60 minutes, several GB. The recipe is kyuz0's, adapted for this repo; the Dockerfile
header lists the three changes (pinned revisions, engine default, docker instead of podman).
`docker buildx build --call=check` parses it clean and all 17 RUN blocks pass `sh -n`.

The build is self-gating, which is worth knowing before reading a failure as a config error:
it runs `test-backend-sched-ring`, greps `DEBUG_HIP_GRAPH_PM4` out of the built
`libamdhip64.so`, and `ldd`-checks the custom libraries for unresolved dependencies. If the
retained-PM4 patch ever disappears from the runtime branch, the build fails rather than
silently shipping a slow image.

For the halo-box engine instead of pwilkin's:

```sh
docker build -f Dockerfile.rocm-10.0-strix-llama \
  --build-arg REPO=https://github.com/halo-box/strix-llama.cpp.git \
  --build-arg BRANCH=master --build-arg ENGINE_COMMIT= \
  -t ...:rocm-10.0-strix-llama-halobox .
```

## Operational warnings carried from the recipe

- **Never set `GGML_CUDA_ENABLE_UNIFIED_MEMORY`.** It routes every allocation through
  `hipMallocManaged`, and under HIP graphs the MTP draft context corrupts — the server dies
  with `init: invalid token` or emits garbage. Unset, graphs + retained PM4 produce
  byte-identical output to the bisection switches and are faster. Note pwilkin's own launcher
  exports `GGML_HIP_ENABLE_UNIFIED_MEMORY`, which no code reads, so the validated host stack
  has always run plain `hipMalloc`.
- **The custom `/opt/strix/lib` must stay on `LD_LIBRARY_PATH` and out of `/etc/ld.so.conf`** —
  it shadows the ROCm 10 SDK's `libamdhip64` / `libhsa-runtime64` by ordering, and adding it
  to `ld.so.conf` breaks that.
- **Bisection switches**, one at a time: `GGML_CUDA_DISABLE_GRAPHS=1`,
  `DEBUG_HIP_GRAPH_CLASSIC_PATH=1`, and `AMD_LOG_LEVEL=3`, which logs
  `[hipGraph][PM4] retained N dispatches in M dwords` per lowered batch — the direct proof the
  fast path is live.
- **Rootless Docker: do not use host networking.** It masks `/sys`, `/sys/class/kfd`
  disappears, and ROCr reports `no ROCm-capable device is detected` even with `/dev/kfd`
  passed through. Publish ports instead — which every build in this repo already does.
- The `model has unused tensor per_layer_token_embd.weight` line at load is **expected** with
  `--load-mode none --lazy-mode on-direct`.
