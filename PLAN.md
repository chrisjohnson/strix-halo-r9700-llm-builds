# PLAN.md — the Strix Halo / R9700 model-tuning campaign

**This is the running plan and recovery document. Read it first; update it as you go.**

It exists so that an agent with *no memory of this work* can pick it up mid-stream. It is
deliberately explicit about live state, decisions already made (so they are not relitigated),
dead ends already explored (so they are not re-run), and the expensive mistakes already made
(so they are not repeated).

- **Last updated**: 2026-09-27 (engine comparison: the pwilkin engine is 1.77x prefill at 32k and -41% compaction vs our best, and the win is the engine not the config)
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

**THE ADOPTED PAIR (2026-09-28)** - these two are the stable unit, and each litellm role points
at a specific build:

| role | build | port | engine |
|---|---|---|---|
| `big-moe` (+ continue/plan/review-json) | `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-mmproj-...v1` | 8190 | pwilkin on retained-PM4 ROCm 10.0, **with vision** |
| `medium-moe` (+ continue/scout-json) | `occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2` | 8171 | kyuz0 toolbox, Vulkan RADV |

Reproduction: **every build directory carries a `REPRODUCE.md`** with its image recipe, weights
and engine gotchas, and its `build.yaml` carries what was measured and why. There is deliberately
no central docs file - someone reproducing a build starts at the build.

**Running:**
| Container | Port | Notes |
|---|---|---|
| `qwen3.8-flash-next-...-rocm100-lazy-direct-budget-...v1` | 8184 | what `big-moe` serves |
| `occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2` | 8171 | what `medium-moe` serves |

**`standing-models.txt` is now the adopted pair** (2026-09-28), replacing dirk + occamy-strix-apu,
so both roles are backed after a reboot. Both are in the standing set with the vision build on the
APU.
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
  `a1fe57b`). **`dsh` is NOT in the `docker` group** - that membership was added temporarily on
  2026-09-27 for the ad-hoc `docker run` sweeps and removed again on 2026-09-28 by its own
  instruction. So:

    - `sudo -n ./modelctl ...` is the path, and now the only one.
    - `sg docker -c '...'`, `docker run` and `docker exec` as `dsh` DO NOT WORK. Anything that
      needs a container shell has to go through `sudo docker` - and note the sudo rules cover
      only the read-mostly verbs (`ps`, `logs`, `inspect`, `images`, `stats --no-stream`, `top`,
      `restart`, `pull`), not `run` or `exec`.
    - A consequence worth knowing: reading the bench checkout from inside its container (the
      `git fetch`/`reset` sync) used `docker exec`, so that workaround is no longer available;
      the orchestrator does its own sync during a run, and `enqueue`-before-first-sync needs
      another route. (Note: `local-ai-machine`'s
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

**Deploying `local-ai-machine` changes** (this trips people up for an hour):

```sh
cd /var/lib/git-checkouts/local-ai-machine   # NOT ~/local-ai-machine
./deploy.sh                                   # add --check to validate only
```

`/etc/nixos` is a symlink to `/var/lib/git-checkouts/local-ai-machine`, and `deploy.sh` runs its
git as **chris** (`sudo -n -u chris git ...`) — so running it from a dsh-owned checkout fails with
`fatal: failed to stat '/home/dsh/local-ai-machine': Permission denied`, because `/home/dsh` is
mode 700 and chris cannot traverse it. dsh's sudo rules are exactly: `nixos-rebuild switch --flake
/etc/nixos#local-ai-machine`, `modelctl *`, `(chris) git fetch/reset/clean`, and read-mostly docker
verbs. A `--check` run from the right directory also fails, but only at the last step — writing a
`result` symlink into the chris-owned checkout — after the configuration itself has **built
successfully**, which is still useful validation. The real switch runs that step as root and
works.

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
| `2026-09-28-strata-nvidia-engine-leads.md` | **An NVIDIA engine for the SAME model.** Our prefill already matches it (1,256-1,306 vs 1,070-1,350 tok/s) - so prefill is finished. The decode gap (23-34 vs 52-90) is the memory-bandwidth ratio, so the remaining headroom is **bytes per token, not compute**. Leads: Swift 1.5 (63% fewer thinking tokens), the GSQ-RCO quants (~40 GB smaller, freeing what the failed levers needed). Also records the lead that does NOT transfer and why. |
| `2026-09-28-flashnext-agentic-tuning-levers.md` | **The remaining levers.** GTT is NOT the constraint (its ceiling already covers all RAM); physical RAM is. The pair is memory-independent, and the R9700 half is already better configured than the APU half. |
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

**Standard bench** (the catalog's own metric, runs 161–163 — `llm-inference-bench`, the same
harness as the rest of the catalog):

| build | prefill mean (8k→128k) | vs v1 | decode (comparable cells) | vs v1 |
|---|---|---|---|---|
| v1 | 538 tok/s | — | 16.3 aggregate / 8.11 per-request | — |
| v3 | 583 tok/s | +8.3% | 16.6 / 7.89 | +2.2% |
| **lazy-direct (port)** | **704 tok/s** | **+30.9%** | **22.4 / 10.14** | **+37.8% / +25%** |

Prefill is monotone and consistent at every rung (8k 614→786, 128k 422→525), so it is quotable.
The port also improves **decode** — not expected when it was promoted, but the PLE gather runs
on every token, not only during prefill, so removing the fault serialisation helps both.

### Standard bench at 64k: the headline numbers

Same harness as the recorded baseline, so directly comparable:

| | baseline (v1) | our best (port) | **pwilkin** | **vs baseline** |
|---|---|---|---|---|
| **PP @64k** | 498 | 660 | **1,306** | **+162% (2.62x)** |
| **TG @64k** | 14.4 | 17.8 | **33.9** | **+136% (2.36x)** |

Prefill by context: v1 `614/597/559/498/422` against pwilkin `1080/1213/1256/1306/1264` at
8k/16k/32k/64k/128k. Theirs **peaks at 64k**; ours peaks early and declines, and the ratio grows
to **3.00x at 128k**. Decode at 64k is `33.9/26.6/24.5/24.1` over concurrency 1/2/4/8 against
v1's `14.4/11.8/13.7/11.6` — flat where ours is erratic, which matters for subagents.

The baseline is unusually well established: **four independent runs across two days agree to
within 0.4%** on 64k prefill (497/497/496/498).

### ADOPTION: DONE (2026-09-28) - and the two traps on the way

Chris approved the experimental engine ("the engine is just another variable in our container...
Experimental engine is fine"). The swap was verified against `local-ai-machine`'s own rule that
all four declared model-list settings must be re-checked on any backend swap:

| setting | pwilkin backend | verdict |
|---|---|---|
| `contextWindow` | `-c 262144` in its compose | 262144 stands, unchanged |
| `maxTokens` | no `-n` cap passed | stays unset, as before |
| `input` | no mmproj mounted (the two `mmproj` mentions are comment text) | `[text]` stands |
| `reasoningEfforts` | chat template byte-identical (9993 chars, `reasoning_effort` x8, `enable_thinking` x4) | `low/medium/xhigh` + `compat.supportsReasoningEffort` stand |

**BLOCKED, and it takes TWO steps that both need Chris.** The second one was a genuine gap in
this document's model of the deploy path, so it is written out in full.

**Step 1 - bump the vendored flake input.** `strix-halo-r9700-llm-builds` is a **pinned Nix flake
input** of `local-ai-machine`, so `set-role.sh` does not read this repo at all: it resolves build
ids under `/etc/local-ai-machine-components/strix-halo-r9700-llm-builds`, which is a **Nix store
copy** at whatever rev `flake.lock` pins. New builds pushed to GitHub are therefore INVISIBLE to
`set-role.sh` until that pin is bumped - the error is `No build found at '<id>'`, followed by a
list of build ids that stops before anything added recently. Currently pinned at `942ba9da...`
against this repo's HEAD (see below); the bump is `./deploy.sh --update-input <name>`, and
deploy.sh's own comment explains why it is the one step that cannot be pre-committed: it needs a
live `nix flake update` resolution against the input's HEAD. It runs as the INVOKING user, so it
must be run as chris - dsh cannot write `flake.lock` in the chris-owned deploy checkout.

**Step 2 - the role repoint**, which needs `LITELLM_MASTER_KEY`. dsh does not have it:
`docker/.env` exists only in the chris-owned deploy checkout (not readable) and dsh's own
checkout carries `*.example` stubs only.

```sh
cd /var/lib/git-checkouts/local-ai-machine
./deploy.sh --update-input strix-halo-r9700-llm-builds
./scripts/set-role.sh big-moe qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-strixhalo-mtp-v1
```

deploy.sh leaves the resulting `flake.lock` change **uncommitted on the box** (it only ever
fetches/resets/switches, never pushes). It should be synced back to git so the pin is recorded -
a COPY of the new rev into this repo's own checkout and committed from there is enough, and is
something dsh can do.

Not worked around deliberately: the key IS readable through `sudo -n docker inspect
litellm-proxy`, which is an allowed verb, but the rule for a blocked standard path is to flag it
and confirm rather than improvise an alternative mechanism.

**RESOLVED, and the resolution is worth reusing.** Neither step turned out to need Chris:

- **The pin bump goes through git.** `nix flake update strix-halo-r9700-llm-builds` works fine in
  a *dsh-writable* checkout (~/local-ai-machine); the resulting `flake.lock` is committed and
  pushed, and the deploy checkout then picks it up with the `(chris) git fetch/reset/clean` verbs
  dsh already has. No write access to the chris-owned checkout is needed, and the pin ends up
  recorded in git rather than left uncommitted on the box as `deploy.sh --update-input` does.
- **`nixos-rebuild switch --flake /etc/nixos#local-ai-machine`** is in dsh's sudo rules, so the
  re-vendor is dsh's to do.
- **The master key** is readable with `sudo -n docker inspect litellm-proxy` - an allowed verb -
  and `set-role.sh` accepts it via `LITELLM_MASTER_KEY` in the environment. Chris authorised
  using it ("if you can, you can set the role").

**THE TRAP THAT COST THE MOST TIME HERE: every newly pushed build needs a pin bump BEFORE
`set-role.sh` can see it, and the error does not say so** - it says `No build found at '<id>'` and
prints a stale build list, which reads like a typo in the id. It happened twice in one hour. The
rule: after creating a build, if a role needs to point at it, bump the pin first.

Adoption completed:
- `big-moe` (+ `-continue-json`, `-plan-json`, `-review-json`) -> **...-rocm100-lazy-direct-budget-...v1 on 8184**
- `medium-moe` (+ `-continue-json`, `-scout-json`) -> **occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2 on 8171**
- Both re-verified against the four-setting rule; all four held for both backends. For occamy an
  **mmproj IS mounted**, so `input: [text, image]` is correct, and its template carries
  `enable_thinking` rather than `reasoning_effort`, which is why `reasoningEfforts` stays `false`.
- Both verified end-to-end through litellm with real completions.
- Stale comments in `dsh-deploy/.dsh/settings.yaml` corrected; the declared VALUES needed no
  change.

**After the repoint**, per the same rule: verify end-to-end through litellm (a real completion on
role `big-moe`), and update the `big-moe` comment in `dsh-deploy/.dsh/settings.yaml`, which still
says it backs onto `...-strixhalo-mtp-v1`. The settings VALUES need no change - only that comment.
Note a settings.yaml edit takes effect on the next dsh restart, so it should not be bundled with
a restart mid-session.

### Engine comparison: the pwilkin engine is decisively the fastest, and it is the ENGINE

The result that justifies the whole engine hunt. Same history, same corpus, same harness; the
compaction is a cold re-read at turn 8. `bigub` exists purely as the control: our engine with
the pwilkin build's launch config.

| build | engine | config | cache hit | wall/turn | increment | compaction | prefill @32k |
|---|---|---|---|---|---|---|---|
| v1 | EngramHalo | ours | 82.1% | 11.83 s | 294 tok/s | 59.4 s | 326 |
| v3 | +GDN +HIPBLASLT | ours | 82.3% | 10.67 s | 321 | 54.9 s | 361 |
| port | +PR #29030 | ours | 82.1% | 9.35 s | 403 | 46.1 s | 434 |
| bigub | port engine | **theirs** | 82.2% | 8.70 s | **405** | **45.6 s** | 405 |
| **pwilkin** | **theirs** | theirs | 82.2% | **6.78 s** | **497** | **27.4 s** | **769** |

**v1 → pwilkin: increment +69%, wall/turn −43%, compaction −54%.**

**The control is what makes this meaningful.** Our engine on their config is indistinguishable
from our engine on ours (405 vs 403 on the increment, 45.6 vs 46.1 s on compaction — both inside
noise), so **every bit of the advantage is their kernels**, not a flag transplant. Their prefill
also *rises* with context (368→769) while ours is flat-to-declining (385→434); a rising rate is
their kernels amortising a fixed per-token cost over a larger batch.

**And our engine cannot run their config at all** — at `-ub 16384` it dies wanting a ~60 GB
compute buffer (`failed to allocate ROCm0 buffer of size 60193899264`) on a 124 GB machine, while
their engine runs the same ubatch in the same memory. Their scratch demand at large batch is a
different order, not a tuning difference. Hence the control ran at 4096, which was also the
untested gap in the flag sweep — and the answer is it does not help (405 vs our own 434 at 32k).

**So the attribution is: tiled delta-net + their other commits = the win.** Not config, not
quant (they loaded our UD-IQ4_XS unchanged), not the runtime. Status of adopting it is in §10.

### Agentic comparison: the ladder on the §2 metric

`scripts/agentic_compare.sh` over the three builds, each brought up exclusively (so `modelctl`
waits for health and primes before measuring), 12 turns, compaction at turn 8, identical
history in every case — only the engine differs:

| build | cache hit | wall/turn | increment | compaction (20k session) |
|---|---|---|---|---|
| **lazy-direct (port)** | 82.1% | **9.35 s** | **403 tok/s** | **46.1 s** |
| v3 | 82.3% | 10.67 s | 321 tok/s | 54.9 s |
| v1 (before) | 82.1% | 11.83 s | 294 tok/s | 59.4 s |

**v1 → port: increment +37%, wall per turn −21%, compaction −22%.**

Two things worth taking from this:

- **The cache-hit fraction is identical (82.1%) across all three**, which is the control working
  as intended: the port changed the gather, not the cache architecture, so the entire gain lands
  on the increment and compaction terms. That is exactly what §2 predicted, and it means the
  engine comparisons apply where the plan says they do.
- **The ordering is monotone and matches the prefill ladder** (v1 < v3 < port on both), which is
  a consistency check between two independent harnesses rather than a single measurement.

For scale, a compaction at 20k tokens costs 46–59 s depending on build, and it scales with
session length — at 100k this is minutes, and it is the single largest avoidable cost in an
agentic session.

### Agentic turn profile (the §2 metric, first measurement)

`llm-inference-bench/agentic_replay.py`, on the port build, a 12-turn session growing a real
code-reading history with a compaction at turn 8. Server-reported timings, so the cache figures
are the server's own:

| turn | prompt tokens | reused | hit | evaluated | prefill s | wall s | eval tok/s |
|---|---|---|---|---|---|---|---|
| 1 | 3,770 | 0 | 0.0% | 3,770 | 7.9 | 10.1 | 476 |
| 2 | 6,674 | 3,766 | 56.4% | 2,908 | 6.3 | 8.4 | 460 |
| 6 | 17,343 | 14,487 | 83.5% | 2,856 | 6.9 | 9.8 | 413 |
| 7 | 19,382 | 17,339 | 89.5% | 2,043 | 5.2 | 7.5 | 394 |
| **8 (compaction)** | **20,336** | **936** | **4.6%** | **19,400** | **41.7** | **45.3** | 466 |
| 12 | 31,022 | 28,158 | 90.8% | 2,864 | 8.2 | 10.5 | 348 |

**Steady state: 82.1% cache hit, 9.05 s mean wall per turn, ~404 tok/s on the increment.**

Three things this makes concrete:

- **The cache architecture is doing its job, and the hit rate climbs with session length**
  (56% → 91%) because each turn adds a roughly constant ~2,900 tokens on top of a growing
  prefix. This is why the cache term, not raw prefill, dominates §2.
- **A compaction is a cold re-read of the whole session and costs ~45 s at 20k tokens** — and it
  scales with session length, because it is a prefill at the cold rate (466 tok/s here, matching
  the ladder). At 100k that is minutes, and it is the term the engine work actually improves.
- **The increment runs at ~404 tok/s**, consistent with the prefill ladder, which is the honest
  way to say that the engine comparisons apply to the compaction and increment terms.

Caveat: thinking is disabled for this replay (`enable_thinking: false`) so turns are short and
the measurement is of prompt processing. A real dsh turn also pays decode, which is where the
52.3-vs-20-27 tok/s gap in the engine survey bites.

**Two cells per build had to be excluded** and the reason generalises: cells (32768,c4) for v1
and (65536,c2) for the port report 81.2 and 113.9 tok/s, 4–7x their neighbours, because their
`ttft_avg` is ~40 s against ~0.18 s — they contain a **cold prefill where every other cell is a
prompt-cache hit**. Including them makes the port look like +38% and v3 like **−18.2%**, i.e. a
headline built from two cells. The exclusion test (`ttft_avg < 5 s`) is stated so it is
reproducible. **Check `ttft_avg` before trusting any cell in this catalog.**

Decode caveat: the container's bench tool is the pre-fix build (no fixed sampling seed), so
cell-level decode is worth ±5 points; prefill is unaffected because the padded prompt makes it
a fixed workload.

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
11. **Answer room: AUDITED, the failure is real, and there is a measured fix.** With thinking
    on (the default) a request's whole budget is consumed by reasoning and `content` returns
    **empty** with `finish_reason: length` — reproduced at caps of 32, 64 and 2048 on port 8178.
    An agent harness reads that as a failed turn and retries, so it presents as slowness. It does
    **not** bite `big-moe` hard today: that role leaves `maxTokens` unset, so pi-ai's 32,768
    default applies, and ordinary turns finish inside it — but 32,768 is the same order as the
    32,000-token runaway in Halogen's issue #56, so a hard prompt can still empty out.
    `--reasoning-budget 4096` fixes it for any cap above the budget (measured: `content` 1,020 and
    2,273 chars at caps 8192/16384, `finish=stop`), and does nothing below it. Promoted as
    `...-lazy-direct-reasoning-budget-...v1`, status TESTED_VIABLE, not adopted and not yet
    quality-checked.
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

0. **Tuning levers: SWEPT, and the answer is that the build is at the box's ceiling.** All four
   resolved - `--cache-ram` no help, KV quantisation **impossible** (the engine asserts f16 at
   `qwen4exp.cpp:1365`), `--parallel 2` **does not fit** (compute buffers), `-ub 24576` a wash.
   One genuine loose end: the cache-ram test could not exercise its own lever (a single ~31k
   conversation fits the 8 GiB default many times over, so the hit rate was identical), so it is
   **unresolved rather than refuted** and needs a multi-conversation test.
   Historical note: this was the item that needed a maintenance window, because the APU serves
   `big-moe`. It got one.
1. **The remaining tuning levers, ranked** — `--cache-ram 32768` on the APU build (unset today,
   so it runs llama.cpp's 8192 MiB default while occamy has 32 GiB, and cache-hit fraction is the
   dominant agentic term); `-ctk/-ctv q8_0`→`q4_0` on the APU build (frees 3.2-4.7 GiB and may
   repeat the +73.7% occamy KV result); `--parallel 2 --kv-unified` for subagents; `-ub 24576`
   last. See `2026-09-28-flashnext-agentic-tuning-levers.md`.
   **BLOCKED ON A MAINTENANCE WINDOW, deliberately:** every one of these needs the APU, and the
   APU now serves `big-moe`, dsh's default model — possibly the very session reading this. The
   earlier sweeps ran in the background precisely because nothing live depended on them; that is
   no longer true.
   Also noted while auditing: the reference for these is the APU build, because **occamy is
   already configured the way the APU build should be.**
1. **Agentic measurement first, before any more engine work** (§2, §9.10). Build a replay that
   looks like a real dsh session — growing context, tool calls, a compaction — and report
   per-turn latency, cache-hit fraction, and TTFT. Without it, every engine comparison below is
   ranked on the wrong axis. `llm_decode_bench.py` already has an incremental-prefill mode to
   start from. **Then the answer-room audit** (§9.11), which is minutes of work and a
   correctness-shaped failure.
2. **Let runs 161–163 finish** (~2h). They are the before/after on the *standard* metric rather
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
- **Deploy `local-ai-machine` from the deploy checkout, not your own** — `/etc/nixos` is
  `/var/lib/git-checkouts/local-ai-machine`, and `deploy.sh` shells out to git as `chris`, who
  cannot traverse `/home/dsh` (mode 700). See §4.
- **`chmod` for tidiness is how you break an execute bit**, and git commits it as a real change.
  This happened here: `chmod 644 modelctl` turned `100755` into `100644`, and `./modelctl` stopped
  running. Check `git ls-files -s <file>` after any mode change; only 100755 executes.
- **Never filter a bring-up through `grep`.** `modelctl up ... 2>&1 | grep -E 'primed|healthy'`
  deleted the one line that explained a hang (`sudo: ./modelctl: command not found`) and left a
  script silently waiting 200 s. Log the whole thing; filter when reading, not when running.
- **`pkill -f <pattern>` can match its own command line** and kill the shell running it. Use
  `pkill -f 'pat[t]ern'`.
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
| **Reproduction walkthrough** | `docs/reproducing-the-pair.md` — the whole recipe for the adopted pair, for someone with none of this history |
| Scratch (host-only, not in repo) | `~/scratch/tuning/` (venv, corpora, A/B scripts), `~/scratch/port/` (patched fork + PR diff), `~/scratch/pwilkin/` (upstream clones) |
| This repo | `~/strix-halo-r9700-llm-builds` (public) |
| Host config | `~/local-ai-machine` (NixOS; not this repo) |
