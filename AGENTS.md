# AGENTS.md — strix-halo-r9700-llm-builds

## What this repo is

The model-engine build catalog, `modelctl`, and the benchmark orchestrator for
`local-ai-machine`. See `README.md` for the full layout; see `builds/README.md` for the
per-build compose-file conventions. This repo is vendored into `local-ai-machine` as a
read-only Nix flake input — see that repo's own `AGENTS.md` "Component deploy mechanism"
section for how the pin gets bumped.

## Day-to-day model operations never need Chris's confirmation

**Starting, stopping, or swapping which model build is running — for testing, for
benchmarking, for anything — is already-standing permission. This includes via
`modelctl` directly on the box, and via `llm-inference-bench` benchmark runs, which do
this automatically as part of their own exclusivity handling.** None of it needs to be
flagged first. Concretely, none of these need to ask first:
- `modelctl up <build-id>` / `modelctl down <build-id>` for any non-standing build.
- Enqueueing a benchmark run (`POST /run` against `llm-inference-bench`'s API), even
  though it will stop other builds sharing the target's GPU (including the always-up
  standing set — confirmed intended behavior, see that repo's `_establish_exclusivity`).
- Adding a new `builds/<id>/` entry for a model+engine combination already downloaded on
  the box, tuning its flags, running it, and recording real results.

**The one thing that IS Chris's call: editing `local-ai-machine`'s own
`standing-models.txt`** — i.e. changing what auto-starts on every real boot. That file
doesn't even live in this repo; it lives in `local-ai-machine`, and that repo's own
`AGENTS.md` hard-stops list covers it. Nothing in this repo's own day-to-day operation
touches it.

This is a clarity fix, not a new rule — the underlying policy never actually required
confirmation for routine model operations; agents had just been hedging in practice.

## Git workflow

**Direct pushes to `main` are explicitly authorized in this repo** — no PR workflow, no
worktree-branch requirement, same as `local-ai-machine` itself. `.github/workflows/
build.yml` runs on every push to any branch (image build+push only builds/pushes on
`main`; the dashboard job is `main`-only too).

**Credentials**: this repo is public, so read access needs nothing special. Two separate
write credentials exist, neither of which is a general-purpose personal credential:
- A dedicated read-write Deploy Key, scoped to this repo only, mounted into the
  `llm-inference-bench` container on the box (`/home/chris/.secrets/strix-halo-r9700-llm-
  builds-deploy-key`) — used only for that container's own automated benchmark-result
  commits, from its own dedicated checkout
  (`/var/lib/git-checkouts/strix-halo-r9700-llm-builds` on the box — never the human box
  checkout, never `local-ai-machine`'s own checkout).
- Whatever GitHub credential a human or agent session is already authenticated with
  (Chris's Mac, `gh auth`) for any other push — e.g. committing a new `builds/` entry,
  fixing `modelctl`, updating CI.

## If the standard deploy/CI path itself is broken, or is repeatedly getting in the way

Sidestepping it is a legitimate thing to do — but flag it and confirm with Chris first
rather than silently improvising a different mechanism, same as `local-ai-machine`'s own
rule. No other repo-specific hard stops beyond this and the standing-models.txt note
above — day-to-day work here is unrestricted.
