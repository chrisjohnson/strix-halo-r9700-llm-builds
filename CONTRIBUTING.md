# Contributing

This is a personal home-lab repo, not one accepting outside contributions — this document
exists for the same audience `AGENTS.md` does: an agent or a future me picking up work
here.

## Workflow

Direct pushes to `main` are the norm — no PR requirement, no worktree-branch convention.
Commit directly, push, done. CI (`.github/workflows/build.yml`) runs on every branch push;
the `llm-inference-bench` image build/push and the dashboard deploy are `main`-only.

See `AGENTS.md` for what does and doesn't need confirmation before acting — short version:
model operations (starting/stopping/benchmarking builds) are unrestricted, editing
`local-ai-machine`'s `standing-models.txt` is the one thing that needs Chris directly, and
that file isn't even in this repo.

## Adding a new build

1. Create `builds/<id>/` (id convention: `<model>-<quant>--<engine>-<backend>-<gpu>-v<n>`,
   see existing entries).
2. `build.yaml` — identity/config, `status:` (`WORKING`/`TESTED_VIABLE`/
   `TESTED_NOT_VIABLE`/etc.), and `notes:` recording what was actually measured and why —
   this is the repo's institutional memory for that build, not just metadata.
3. `docker-compose.yaml` — single service, `container_name` matching the build id exactly,
   port allocated per `builds/README.md`'s ranges, no `name: docker` project override
   needed (`modelctl` supplies `-p` itself).
4. `modelctl up <id>` to bring it up, confirm it's healthy, then either drive a real
   benchmark run through `llm-inference-bench` or record a manual result directly in
   `build.yaml`'s `notes:`.
5. If this build is meant to become part of the standing set, that's a separate,
   Chris-confirmed edit to `local-ai-machine`'s `standing-models.txt` — not something this
   repo's own history determines on its own.

## Fleet board

`.fleet/board/` tracks in-progress work here — see `local-ai-machine`'s `AGENTS.md` for
the fleet conventions (claim/signal/decision-log discipline) this board follows.
