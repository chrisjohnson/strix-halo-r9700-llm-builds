# PLAN.md — the Strix Halo / R9700 model-tuning campaign

**This is the running plan and recovery document. Read it first; update it as you go.**

It exists so that an agent with *no memory of this work* can pick it up mid-stream. It is
deliberately explicit about live state, decisions already made (so they are not relitigated),
dead ends already explored (so they are not re-run), and the expensive mistakes already made
(so they are not repeated).

- **Last updated**: 2026-09-27 (agentic reframe of the goal added to §2)
- **Sibling documents**: `AGENTS.md` (repo permissions/conventions), `README.md` (repo layout),
  `builds/README.md` (per-build conventions), `knowledge/decisions/` (why, per decision),
  `knowledge/research/` (what was measured, per investigation).
- **Keep it current**: update section 1 (live state) and section 10 (the plan) at every
  milestone. When a decision is made, add an entry under `knowledge/decisions/` *and* a row in
  section 6 here. When an investigation concludes, add `knowledge/research/` *and* a row in
  section 7.

---

## 1. Where things stand right now

Snapshot 2026-09-27, git HEAD `1e3de30`, working tree clean, both repos clean.

**Running:**
| Container | Port | Notes |
|---|---|---|
| `qwen3.8-flash-next-...-strixhalo-mtp-v1` | 8152 | the standing APU build; litellm role `big-moe` points here |
| `occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2` | 8171 | the standing R9700 build |
| `litellm-proxy`, `open-webui`, `searxng`, `grafana`, `prometheus`, `caddy`, … | — | not part of this work |

**In flight:** `llm-inference-bench` runs **161** (v1, running), **162** (v3, queued), **163**
(lazy-direct port, queued) — the standard-bench before/after ladder. ~40 min each. A background
watcher job polls them and exits when all are terminal.

**Known-broken / stale, not yet fixed:**
- litellm roles `medium-moe` (→ dead 8205) and `medium-dense` (→ stopped dirk 8161) point at
  nothing.
- The bench orchestrator's checkout only syncs *during* a run, so a freshly pushed build cannot
  be enqueued until something syncs it by hand (see §11).
- Disk: 505 GB free of 1.9 TB.

---

## 2. The mission

Tune `local-ai-machine` so its two models run at **full 256k context with maximum useful cache,
no RAM or VRAM left on the table, and a stable experience**:

- **`qwen3.8-flash-next`** — slow/smart, Strix Halo APU (`gfx1151`, ~256 GB/s, 124 GiB unified).
- **`occamy`** — fast/light, R9700 eGPU (32 GiB dedicated GDDR6, its own memory).

**The goal, restated 2026-09-27 (supersedes "maximise tok/s"): the target is overall *agentic*
performance — these models run as a drop-in replacement for cloud DeepSeek behind the same kind
of dsh sessions Chris already runs.** A dsh session is a long conversation that grows: every turn
re-sends the whole history plus tool definitions and tool results, and a compaction periodically
re-reads all of it cold. So the metric is **end-to-end latency of a turn in a growing
conversation**, which decomposes into three terms and one gate:

1. **Cache-hit fraction** — does the next turn resume where the last one stopped? This is the
   largest term by far, and the one we have measured *incidentally* rather than tracked. A
   production server's own numbers show a **44x spread between its best and worst cache mode**
   (~2 s vs ~88 s for a follow-up turn at 100k), which dwarfs any kernel win in this repo's
   history. See `knowledge/research/2026-09-27-halogen-agentic-tuning-lessons.md`.
2. **Increment prefill rate** — the ~1–4k new tokens a turn adds. This is where our measured
   deficit actually is (~235 tok/s effective on the increment vs ~500 for a production server),
   and where the engine work (PR #29030, tiled delta-net) moves the needle.
3. **Decode with speculation** — streaming the tool call. Ours ~20–27 tok/s against ~52.
4. **The gate: reliability.** A turn that returns an *empty answer* because the thinking block
   consumed the whole budget is worse than a slow turn, and it presents to the harness as a
   retry. **Un-audited on our stack** — see §9.

Standing rules that came out of it: prefer *measured* wins; promote every improvement to its own
versioned build directory rather than editing a committed build in place; every build version
gets its own host port; record the numbers with the build. **And measure the metric that is
actually experienced** — a prefill tok/s figure that improves a term the harness never waits on
is not a win.

---

## 3. Ground rules, permissions, credentials

- **Chris's call only**: editing `local-ai-machine`'s `standing-models.txt` — i.e. what
  auto-starts on boot. Nothing else.
- **Already-standing permission** (do not ask): `modelctl up/down`, enqueueing benchmark runs,
  adding `builds/<id>/` entries, tuning flags, running real measurements. `AGENTS.md` is explicit.
- **Direct pushes to `main` are authorized** in both repos — fast-forward only. Never
  force-push or rewrite pushed history; if diverged, stop and ask.
- **Never edit or delete** a committed build in place except to *correct a factual claim*
  (there is precedent: commit `c9934cf` withdraws a wrong claim; the old text is quoted, not
  silently edited).
- **Access**: `sudo -n ./modelctl ...` works (a sudoers rule allows
  `/home/dsh/strix-halo-r9700-llm-builds/modelctl *`, added in `local-ai-machine` commit
  `a1fe57b`, which also marked `dsh`'s `docker` group membership TEMPORARY). Since `dsh` is in
  the `docker` group, plain `modelctl` also works and docker is reached via
  `sg docker -c '...'` rather than `sudo docker`. (Note: `local-ai-machine`'s
  `configuration.nix` comment above that rule still says it is "Not reachable today — modelctl
  talks to the docker socket, which dsh can't open". That comment is **stale**: both paths have
  worked all session, since `sudo` makes modelctl run as root and the docker-group membership
  covers the unprivileged case. Trust the behaviour, not the comment.)
- **Images are built locally**, not by CI. CI only builds the `llm-inference-bench` image.

---

## 4. How to operate

```sh
cd ~/strix-halo-r9700-llm-builds

# models
sudo -n ./modelctl list                     # catalogue: id, status, port
sudo -n ./modelctl up   <build-id>          # start (own port from its compose)
sudo -n ./modelctl down <build-id>
sudo -n ./modelctl up --exclusive <id>      # stops builds sharing derived.target_gpu

# benchmark orchestrator (container llm-inference-bench)
curl -s http://127.0.0.1:8092/state | jq '.runs | to_entries | map(select(.value.status=="running" or .value.status=="queued"))'
curl -s http://127.0.0.1:8092/runs/<id>
curl -s -X POST http://127.0.0.1:8092/runs -H 'Content-Type: application/json' \
     -d '{"runs":[["<build-id>"]]}'          # enqueue one run
# /runs/<id>/close marks a run terminal; it does NOT kill the subprocess - see §11

# the harness (repo-relative, this is the tool the orchestrator also uses)
~/scratch/tuning/venv/bin/python llm-inference-bench/llm_decode_bench.py --help
```

**Backend endpoints**: flash-next v1 `127.0.0.1:8152`, occamy v2 `127.0.0.1:8171`. `GET /health`,
`GET /props`, `GET /metrics`.

---

## 5. What we've done (chronological)

1. **Rescued a broken opencode session.** `~/.local/share/opencode/opencode-stable.db`, session
   `ses_f1e8a695effexdiSmnjJjCAKhc`. Its failure was **not** rate limiting: HTTP 403
   `FreeTierError` from `opencode.ai/zen/v1/chat/completions`, `isRetryable: false`, with
   `opencode auth list` showing **0 credentials** (anonymous free tier). Fix is
   `opencode auth login` or repoint at litellm. The session's own conclusion — that a
   `qwen3.8-flash-next` prefill floor was suppressing throughput — turned out to be **correct**.
2. **Found and fixed a measurement-harness bug.** Prefill rates were computed as
   `requested_ctx / prefill_time`, but the request carried padding in *characters* budgeted at
   4 chars/token while real text is ~2.6–3.6 — inflating rates up to 2.2x. Fixed by reading the
   server's own `timings` with `cache_prompt: false`. Committed.
3. **Found the padding trap.** The harness re-sent one truncated base plus periodic filler, so
   at every context the prompt was **327 distinct trigrams** — which cannot exercise the
   model's 3-gram-keyed PLE/engram table. Replaced with a combinatorial seeded generator
   (17,610 distinct trigrams at 256k). See `2026-09-27-prefill-bench-padding-trap.md`.
4. **Characterised the prefill floor**: `ms/token = 2.576 + 562/tokens` — a constant ~2.58 ms
   per token regardless of context, ~37% of full-context per-token cost. See
   `2026-09-27-flashnext-prefill-constant-floor.md`.
5. **Swept the launch flags**; found `ROCBLAS_USE_HIPBLASLT=1` worth +4.6–9.5%; found
   `-ub 8192` and `--tensor-read-lazy off` both catastrophic (memory); see
   `2026-09-27-flashnext-flag-sweep.md`.
6. **Swept the memory budget** for occamy on the R9700 and for flash-next at 256k; `q4_0` KV on
   occamy is worth **+73.7% prefill @8k, +51.9% @32k** vs `q8_0`. See
   `2026-09-27-flashnext-occamy-256k-memory-budget.md`.
7. **Built the bench harness's own measurement of decode** and established an **8–11% run-to-run
   noise floor that a fixed sampling seed does not remove** — so nothing below ~10% decode
   difference is resolvable here. `2026-09-27-flashnext-decode-vs-context.md`.
8. **Promoted the swept variants** as catalog builds (`1730635`) and **ran the standard bench**
   on the ones lacking data: runs 154–160.
9. **Recovered a lost benchmark result.** Run 155's 42-minute measurement completed but its
   *commit* failed — caused by this author deleting what looked like an orphaned partial log
   from a killed run, which the orchestrator had *just* committed, leaving a tracked-file
   deletion that made `git pull --rebase` refuse. Recovered as `dbd9ee5` after verifying
   16/16 cells, `target_launch_config`, and md5 equality. Commit message records the lesson.
10. **Measured `GGML_HIP_GDN_CHUNK=1`** — a lever this work had wrongly "refuted" by grepping a
    12 KB launcher shim instead of the real library (`c9934cf` retracts it). Worth **+7.4–10.7%**.
    Promoted with HIPBLASLT as build **v3** (`787efda`).
11. **Ported upstream PR #29030** (direct-read lazy gather) onto the EngramHalo fork. The
    original recommendation against it is formally retracted; it is worth **+21.9–29.1% over
    v3**. Promoted as the **lazy-direct** build (`9e38bfd`), with the PR vendored as a patch
    plus its own Dockerfile because the PR is still open upstream.
12. **Made the image reproducible** (`f7fe4c0`): pinned the fork commit, documented all three
    Dockerfiles, added a corpus builder, and stated three honest gaps (see §9).
13. **Surveyed the wider engine landscape** after a community result claimed ~1.2k t/s prefill
    (`1e3de30`). Vendored a **docker** Dockerfile for the retained-PM4 stack and documented
    `kyuz0/gufo`, which claims **1,628 tok/s pp**. See
    `2026-09-27-strix-halo-engine-landscape.md`.

---

## 6. Decisions made (do not relitigate without new data)

| Decision | Entry |
|---|---|
| Port PR #29030 — **yes**, +21.9–29.1%. Earlier "don't" entry retracted | `2026-09-27-29030-port-adopted-measured-win.md` |
| ~~Deprioritise the PR #29030 port~~ — **RETRACTED** | `2026-09-27-29030-port-deprioritised-measure-floor-first.md` (status: superseded) |
| Two-model topology and the measured configs for each | `2026-09-27-two-model-topology-and-measured-configs.md` |
| Keep the **existing** bench tool for new runs, so results stay comparable with the ~100 in the catalog; a basis-fixing migration is a separate decision | commit message + build notes |

---

## 7. Research done

All under `knowledge/research/`. The ones that bear on current decisions:

| Note | What it establishes |
|---|---|
| `2026-09-27-strix-halo-engine-landscape.md` | **The other engines, and where the remaining speed is.** `kyuz0/gufo` 1,628 pp; pwilkin/strix-llama ~1,200; the tiled delta-net is 2.37x and we don't have it |
| `2026-09-27-halogen-agentic-tuning-lessons.md` | **The reframe.** A production Flash-Next server's cache-mode spread is 44x; the answer-room failure mode (empty answers on compaction); disk-persistent prompt cache; the shared-KV-pool concurrency model. Read before planning any further tuning. |
| `2026-09-27-prefill-bench-padding-trap.md` | Repeated filler cannot exercise the PLE table; rates inflate. **Read before designing any prefill measurement.** |
| `2026-09-27-flashnext-prefill-constant-floor.md` | The 2.58 ms/token floor, and that it is *not* mmap fault overhead |
| `2026-09-27-flashnext-flag-sweep.md` | HIPBLASLT win; `-ub 8192` and `lazy off` losses; the GDN correction |
| `2026-09-27-flashnext-occamy-256k-memory-budget.md` | q4_0 KV win on occamy; memory ceilings |
| `2026-09-27-flashnext-decode-vs-context.md` | The 8–11% decode noise floor |
| `2026-09-27-flashnext-incremental-prefill-and-prompt-cache.md` | Warm-cache incremental prefill numbers |
| `2026-09-27-flashnext-...` (others) | Supporting measurements |

---

## 8. The numbers

**Prefill, real corpus, single stream, server-reported timings** (`--context-file`,
`--prefill-repeats`, seeded padding):

| requested | tokens | v1 | v3 | **lazy-direct (port)** | port vs v1 |
|---|---|---|---|---|---|
| 1k | 1,438 | 326 | 366 | 385 | +18.1% |
| 2k | 2,409 | 337 | 387 | 451–483 | +33.8 – +43.3% |
| 4k | 5,073 | 370 | 414 | 473 | +27.8% |
| 8k | 9,399 | 371 | 416 | 473–504 | +27.5 – +35.8% |
| 32k | 35,300 | 326 | 361 | 415–434 | +27.3 – +33.1% |

Ranges are two measured runs, not an error bar. Attribution: `GGML_HIP_GDN_CHUNK=1`
+7.4–10.7%; `ROCBLAS_USE_HIPBLASLT=1` +4.6–9.5%; PR #29030 +21.9–29.1% on top of those.

**Decode is not claimed** — the noise floor is 8–11%.

**Page-cache warmth was controlled**, not assumed: v3 re-measured on a warm cache gave
374/407/356 against its earlier 387/416/361, so it gains nothing from warmth, while the port
gave 483/504/434.

---

## 9. Open threads and known gaps

1. **The checked-in Dockerfile did not produce the measured image.** It came from an equivalent
   COPY-based build against a local checkout of the same commit with the same patches, and the
   checked-in clone-based one **has not been executed**. Unverified.
2. **`Dockerfile.rocm-7.14` (v1/v2/v3) does not pin a commit** — pre-existing gap, left alone
   because three recorded builds reference it.
3. **The measurement corpus is not committed, and cannot be** — it spans `local-ai-machine` and
   contains credential-shaped strings, and this repo is public. `scripts/build_bench_corpus.sh`
   gives a deterministic equivalent from this repo alone; absolute rates shift on it.
4. **The per-buffer-mmap patch is absent from the lazy-direct build** (it and PR #29030 both
   rewrite `llama-model-loader.{cpp,h}` — mutually exclusive). So that A/B measures "PR present,
   patch absent" against v3, which has both. **A control build with neither would isolate the PR
   and has not been done.**
5. **Nothing has been adopted.** v1 still runs 8152 and is still what litellm `big-moe` points at.
   Adopting the lazy-direct build is an *engine* change, not a flag, so it should be deliberate.
6. **Batch width is unexplored on our side.** The port's benefit scales with ubatch; we proved
   `-ub 8192` fails *with mmap*, but the pwilkin/gufo stacks run `--load-mode none` with
   `-ub 16384`, which is a different memory layout entirely.
7. **The tiled gated delta-net (2.37x) is not ported** and is the single largest known win.
8. litellm `medium-moe` / `medium-dense` point at dead backends.
9. Dirk (the R9700 model) is stopped and cannot coexist with occamy on the R9700.
10. **The agentic loop has never been measured end-to-end.** No per-turn latency, cache-hit
    fraction, or TTFT numbers exist for a realistic growing conversation with tool calls and a
    compaction. Everything so far is single-shot prefill/decode. This is the biggest measurement
    gap given the goal in §2.
11. **The "answer room" is un-audited, and the audit so far says we have none.** If a request's
    answer cap is consumed by the thinking block, some servers return `finish_reason: length`
    with **empty `content`** — and an agent harness reads that as a failed compaction and
    retries. Confirmed 2026-09-27: **none of our flash-next builds sets ANY reasoning flag** —
    no `--reasoning-format`, no `--reasoning-effort`, no `--reasoning-budget` — while the build
    supports all of them plus `--reasoning-budget-message` (llama.cpp's answer-room primitive)
    and the template carries both `reasoning_effort` and `enable_thinking`. So thinking is
    unbounded and the wire format is not DeepSeek's. Two candidate build variants, both cheap:
    `--reasoning-format deepseek` for API-shape parity with cloud DeepSeek, and a thinking bound
    for compaction safety. Halogen's advice is to **bound** thinking at `xhigh`, not lower it.
12. **llama.cpp has no disk-persistent prompt cache.** `--cache-ram` is memory-only, so a dsh
    session resumed after a *model* restart re-prefills its whole history. A production server
    persists it (~27 KiB/token) and turns ~40 s cold into a few seconds. No fix visible on our
    side; worth knowing it is a real cost.
13. **Concurrency is architecturally underexplored.** Our `--parallel` work allocates per-slot
    context; a production server shares one KV pool across conversations and separates "max per
    request" from "positions resident", which is how several full-length conversations fit.
    dsh subagents make this a real axis.

---

## 10. The plan

Ordered. Costs are real; don't start a heavy one while a benchmark is running (§11).

0. **Agentic measurement first, before any more engine work** (§2, §9.10). Build a replay that
   looks like a real dsh session — growing context, tool calls, a compaction — and report
   per-turn latency, cache-hit fraction, and TTFT. Without it, every engine comparison below is
   ranked on the wrong axis. `llm_decode_bench.py` already has an incremental-prefill mode to
   start from. **Then the answer-room audit** (§9.11), which is minutes of work and a
   correctness-shaped failure.
1. **Let runs 161–163 finish** (~2h). They are the before/after on the *standard* metric rather
   than the custom prefill ladder. Report the result.
2. **Build the retained-PM4 image**:
   `docker build -f docker/pwilkin-strix-halo/Dockerfile.rocm-10.0-strix-llama -t ...:rocm-10.0-lazy-direct .`
   40–60 min, CPU+disk heavy. Then a `builds/` entry using the documented flags
   (`--load-mode none --lazy-mode on-direct -ctk f16 -ctv f16 -b 16384 -ub 16384 --jinja`,
   **never** `GGML_CUDA_ENABLE_UNIFIED_MEMORY`), with **our** weights so the comparison is
   engine-vs-engine.
3. **Pull and A/B `kyuz0/gufo`** — cheapest high-ceiling option, no build, best published
   number (1,628 pp). OpenAI-compatible server, so it could sit behind litellm if it holds up.
4. **Revisit batch width on our own lazy-direct build** (`-ub` > 2048, with `--load-mode none`),
   since §7 says the port's value scales with ubatch. Cheapest of the remaining wins.
5. **Chase the tiled gated delta-net** (2.37x). Kernel work against a different fork — the
   largest but most expensive win.
6. Fix the litellm dead roles; decide whether to adopt an engine.

**Rule for all of it**: every candidate becomes its own build directory and is compared on the
same hardware with the same harness and the same weights. Divergent setups side by side is the
point, not a problem.

---

## 11. Gotchas learned the hard way

- **`grep -c` counts lines, and a binary has almost no newlines** — so `grep -aoc PATTERN bigbin`
  returns 0 or 1 regardless of the truth. It produced a confident, wrong "this lever does not
  exist". Use `grep -ao PATTERN file | wc -l`, and `ls -la` first: **`/usr/local/bin/llama-server`
  in these images is a 12 KB launcher shim** — the code is in `/usr/local/lib64/libllama.so`.
- **Never touch the bench checkout while the orchestrator is active**, not even to tidy. Deleting
  a file the orchestrator had just committed left the worktree dirty and broke the next run's
  `git pull --rebase`. The checkout is `/var/lib/git-checkouts/...`, owned by `chris`.
- **`/runs/<id>/close` does not stop the work.** To actually kill a run, find the
  `llm_decode_bench` PID *inside the container* (the slim image has no `ps`/`pkill` — walk
  `/proc/*/cmdline`) and `kill` it; the worker then marks the run failed and moves on.
- **The orchestrator refuses to benchmark builds marked `TESTED_NOT_VIABLE`**
  ("known-failed (build.yaml status)"), and refuses to commit results with zero completed cells
  ("refusing to trust empty data"). Both are features.
- **The bench checkout only syncs *during* a run**, so `POST /runs` validates against a stale
  tree — sync it by hand first, then enqueue.
- **`--tensor-read-lazy` was renamed to `--lazy-mode`** by PR #29030, and `on` now means *direct
  reads*. There is no `on-direct` value in our build. A container passing the old name with the
  new image will not start.
- **Never set `GGML_CUDA_ENABLE_UNIFIED_MEMORY`** on the retained-PM4 stack — it routes through
  `hipMallocManaged` and corrupts MTP output (garbage tokens or `init: invalid token`).
- **`/opt/strix/lib` must stay on `LD_LIBRARY_PATH` and out of `ld.so.conf`** — it shadows the
  ROCm SDK's `libamdhip64`/`libhsa-runtime64` by ordering.
- **Rootless Docker must not use host networking** on this box's ROCm containers; it masks
  `/sys/class/kfd`. Publish ports (every build here already does).
- **This box's shell tools default to 60 s** — pass a longer timeout explicitly for container
  starts and image work, or use a background job.
- **Don't build or pull images while a benchmark is running**: it contends on CPU *and disk*, and
  the lazy reader does `pread()` from disk, so it corrupts exactly the numbers being measured.

---

## 12. Where everything lives

| Thing | Path |
|---|---|
| Build catalog | `builds/<id>/{build.yaml,docker-compose.yaml,benchmarks/}` |
| Model engines (docker) | `docker/qwen4exp-strix-halo-mtp/` (ROCm 7.14 + EngramHalo), `docker/pwilkin-strix-halo/` (ROCm 10.0 + retained-PM4) |
| Benchmark orchestrator | `llm-inference-bench/` (`app/orchestrator.py`), API `127.0.0.1:8092` |
| The bench harness | `llm-inference-bench/llm_decode_bench.py` |
| Model control | `./modelctl` |
| Decision log | `knowledge/decisions/` |
| Investigation log | `knowledge/research/` |
| Corpus builder | `scripts/build_bench_corpus.sh` |
| Scratch (host-only, not in repo) | `~/scratch/tuning/` (venv, corpora, A/B scripts), `~/scratch/port/` (patched fork + PR diff), `~/scratch/pwilkin/` (upstream clones) |
| This repo | `~/strix-halo-r9700-llm-builds` (public) |
| Host config | `~/local-ai-machine` (NixOS; not this repo) |
