# Reproducing the flash-next + occamy pair

Two builds on one box, each with its own GPU, fronted by litellm roles. This is the whole recipe:
what to build, what to download, what to run, and what numbers to expect. It is written for
someone with the same hardware who has none of this repo's history.

If you only read one thing: **the two halves are memory-independent**, so build and tune them
separately. flash-next lives in the APU's unified host RAM; occamy lives in the R9700's own
GDDR6 and touches almost no host memory.

## Hardware

| | |
|---|---|
| APU | AMD Ryzen AI MAX+ 395 / Radeon 8060S, `gfx1151`, 124 GiB unified, ~256 GB/s |
| eGPU | AMD Radeon AI PRO R9700, 32 GiB GDDR6 |
| Device order | `card0` = R9700, `card1` = APU. ROCm device numbering is the OPPOSITE of Vulkan's |
| Kernel | anything recent enough for ROCm 10.0 userspace; **no special parameters needed** |

Measured memory split with both running:

```
host RAM     124 GiB total, 115 used, 9 available, 12 buff/cache
card0 R9700  vram 31.9/29.0 GiB     gtt 124.0/1.7 GiB
card1 APU    vram  1.0/ 0.2 GiB     gtt 124.0/84.6 GiB
```

The APU's 84.6 GiB of GTT *is* the model, mapped out of host RAM. GTT's ceiling already covers
the whole pool, so **there is no GTT or `ttm.pages_limit` setting worth changing** — the binding
constraint is physical RAM, not the mapping.

## The two builds

| role | build id | port | engine |
|---|---|---|---|
| `big-moe` | `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-strixhalo-mtp-v1` | 8184 | pwilkin llama.cpp on retained-PM4 ROCm 10.0 |
| `medium-moe` | `occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2` | 8171 | kyuz0 toolbox, Vulkan RADV |

Every build gets **its own host port**, and the port is read from its own compose file.

### Image 1 — `strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct`

Built locally; not in any registry. ~7.6 GB, 40–60 minutes, several GB of build cache.

```sh
cd docker/pwilkin-strix-halo
docker build -f Dockerfile.rocm-10.0-strix-llama \
  -t strix-halo-r9700-llm-builds/pwilkin-strix-halo:rocm-10.0-lazy-direct .
```

The Dockerfile pins both upstream revisions (`ROCM_SYSTEMS_COMMIT`, `ENGINE_COMMIT`) to the exact
commits its numbers were measured with — `pwilkin/rocm-systems@ilintar-experiments` and
`pwilkin/llama.cpp@strix-halo`. It **self-gates**: it runs `test-backend-sched-ring`, greps
`DEBUG_HIP_GRAPH_PM4` out of the built `libamdhip64.so` (proving the retained-PM4 patch is really
in), and `ldd`-checks the custom libraries for unresolved dependencies. A build that passes has a
genuine chance of working; a build that fails loudly is better than one that silently ships slow.

**Two things in that image will stop it dead on a different box, both fixed in the compose:**
- It bakes `HSA_OVERRIDE_GFX_VERSION=11.5.1`, which on this hardware makes ROCr find **no device
  at all**. The compose overrides it to empty, which HSA reads as unset.
- Never set `GGML_CUDA_ENABLE_UNIFIED_MEMORY` — it routes allocation through `hipMallocManaged`
  and corrupts MTP output (garbage, or `init: invalid token`).

### Image 2 — `docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv`

External and public. `docker pull` it. Nothing is built here.

## Models

All weights live under `/var/lib/ai-models/<name>/`, each directory carrying a
`.download-complete` marker that `modelctl` checks before starting a build. Downloads are
declared in `local-ai-machine`'s `configuration.nix` `models` list and fetched by a systemd unit —
add an entry there rather than hand-fetching, so the set stays reproducible. The equivalent
manual commands:

```sh
# flash-next target, 88 GiB, 3 shards
hf download unsloth/Qwen3.8-Flash-Next-GGUF 'UD-IQ4_XS/*' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-iq4xs

# its MTP draft head - the SHARED variant; the non-shared file is a different head
hf download unsloth/Qwen3.8-Flash-Next-GGUF \
  'MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf' \
  --local-dir /var/lib/ai-models/qwen3.8-flash-next-mtp-shared-q8

# occamy, one file, plus its vision projector
hf download <occamy-repo> 'occamy-1.0-mtp-Q4_K_M.gguf' \
  --local-dir /var/lib/ai-models/llamacpp-occamy-1.0-mtp-q4
```

Note the nested path on the MTP head: `hf download` preserves the repo's directory structure, so
it lands at `<dir>/MTP/mtp-...gguf` and the compose mount says so.

**Which quant matters more than it looks.** flash-next's `UD-IQ4_XS` is a *dynamic* quant — the
format varies per tensor. That is fine for llama.cpp, which supports every format, but **gufo
refuses it outright** (`tensor blk.0.ffn_gate_exps.weight has unsupported format IQ3_S`), and
gufo's kernels support exactly one quant for this model. Engines differ in quant *breadth*, not
only speed.

## Running it

```sh
sudo ./modelctl up --exclusive <build-id>     # waits for health, then primes
sudo ./modelctl list                          # every build, its status and port
sudo ./modelctl down <build-id>
```

`--exclusive` scopes by `derived.target_gpu` in the build's `build.yaml`. `up` waits for `/health`
and then sends a priming completion, so the first real request does not pay start-up cost.

Point the roles at the builds. `local-ai-machine`'s `scripts/set-role.sh` reads the port from the
build's compose and updates litellm's DB live; it also auto-updates the paired JSON siblings:

```sh
./scripts/set-role.sh big-moe    qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-strixhalo-mtp-v1
./scripts/set-role.sh medium-moe occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2
```

**If it answers `No build found at '<id>'`, the id is not wrong — the flake pin is stale.** This
repo is a pinned Nix flake input of `local-ai-machine`, and `set-role.sh` resolves ids under
`/etc/local-ai-machine-components/strix-halo-r9700-llm-builds`, a Nix store copy of whatever rev
`flake.lock` names. Newly pushed builds are invisible until that pin moves:

```sh
cd <a dsh-writable local-ai-machine checkout>
nix flake update strix-halo-r9700-llm-builds
git add flake.lock && git commit -m 'flake.lock: bump builds' && git push
cd /var/lib/git-checkouts/local-ai-machine && ./deploy.sh
```

## Numbers to expect

Prefill, `llm-inference-bench`, and the two engines measured against each other on identical
weights and identical prompts. **`big-moe` is the flash-next column.**

| requested ctx | flash-next v1 (old build) | flash-next (this build) | multiplier |
|---|---|---|---|
| 8k | 614 tok/s | 1080 | 1.76x |
| 16k | 597 | 1213 | 2.03x |
| 32k | 559 | 1256 | 2.25x |
| 64k | 498 | **1306** | **2.62x** |
| 128k | 422 | 1264 | 3.00x |

Decode at 64k: **33.9 tok/s** at concurrency 1, and flat (26.6 / 24.5 / 24.1) out to 8 concurrent.
Against the old build's 14.4 that is **+136%**.

Agentic, which is what these roles exist for — a 12-turn session with a compaction at turn 8:

| | flash-next v1 | this build |
|---|---|---|
| increment per turn | 294 tok/s | **497** |
| wall per turn | 11.83 s | **6.78 s** |
| compaction (20k session, cold) | 59.4 s | **27.4 s** |

Reproduce with `llm-inference-bench/agentic_replay.py` (needs a server) and
`scripts/pp_tg_at_context.sh <port> <ctx>` for a single PP/TG point.

**Read the shapes, not just the points.** This engine's prefill *rises* with context to 64k
where the old build's peaked early and declined; that is the whole reason the advantage grows
with session length. And its decode is flat across concurrency where the old build's was erratic —
which matters more for subagents than the peak number does.

## Known gaps, stated rather than glossed

1. **The committed `docker/qwen4exp-strix-halo-mtp/Dockerfile.rocm-7.14-lazy-direct` has never
   been executed.** The `:rocm-7.14-lazy-direct` image was produced from an equivalent COPY-based
   Dockerfile against a local checkout of the same commit with the same patches, because that
   port lived on a branch with no remote. Image 1 above is a different, verified recipe; this gap
   affects only the EngramHalo-based builds.
2. **`docker/qwen4exp-strix-halo-mtp/Dockerfile.rocm-7.14` does not pin a commit** — it clones
   the fork's branch head, which is third-party and can move. The `-lazy-direct` variant does pin.
3. **The measurement corpus is deliberately not committed.** It spans a private repo and contains
   credential-shaped strings, and this repo is public. `scripts/build_bench_corpus.sh` builds a
   deterministic equivalent from this repo alone; absolute rates shift slightly on it, the
   build-to-build comparisons do not.
4. **`set-role.sh` needs `LITELLM_MASTER_KEY`**, which lives in the deploy checkout's
   `docker/.env`. It can be read with `docker inspect litellm-proxy` (an allowed verb) and passed
   in the environment, but it is not in a fresh dev checkout.
