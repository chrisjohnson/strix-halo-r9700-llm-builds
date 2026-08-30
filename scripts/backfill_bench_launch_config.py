#!/usr/bin/env python3
"""Backfill target_launch_config into historical llm-inference-bench result
JSONs, reconstructed via git archaeology rather than live docker inspect
(the containers that produced these results are long gone).

This repo (strix-halo-r9700-llm-builds) was extracted from local-ai-machine
on 2026-08-27 as a single squashed commit - anything benchmarked before that
date has no per-run history *here*, but local-ai-machine's own git history
still has it (with builds/ directory renames along the way, e.g. the
2026-08-20 "-strix-apu" suffix rename). Strategy per JSON file:

  1. search local-ai-machine's history by basename (the timestamped
     filename is unique across all history) with --follow, which resolves
     renames automatically; take the OLDEST matching commit as the true
     "added" commit, using the path that commit actually used (not
     necessarily today's path)
  2. take that commit's PARENT - the orchestrator always git-resets to
     HEAD before running a benchmark and commits results right after, so
     the compose file at the parent is what was actually live at run time
  3. read builds/<id>/docker-compose.yaml (using the historical path) as
     of that parent commit, in local-ai-machine's history
  4. if nothing is found there (the file was created directly in this repo
     after the 2026-08-27 extraction, e.g. via a manual copy, not a real
     benchmark run through the orchestrator here), fall back to searching
     THIS repo's own history the same way

Idempotent: skips any file that already has a non-null target_launch_config
(e.g. runs produced after the live-capture code shipped).
"""
import json
import subprocess
import sys
from pathlib import Path

THIS_REPO = Path(__file__).resolve().parent.parent
OLD_REPO = Path("/var/lib/git-checkouts/local-ai-machine")


def run(cwd: Path, cmd: list[str]) -> str:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=False
    ).stdout


def find_origin(repo: Path, basename: str) -> tuple[str, str] | None:
    """Return (origin_commit, path_at_that_commit) or None."""
    out = run(repo, ["git", "log", "--follow", "--format=%H", "--name-only",
                      "--", f"**/{basename}"])
    entries = []  # (commit, path) newest-first
    lines = out.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line and len(line) == 40 and all(c in "0123456789abcdef" for c in line):
            commit = line
            # next non-blank line is the path
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            path = lines[j].strip() if j < len(lines) else None
            if path:
                entries.append((commit, path))
            i = j + 1
        else:
            i += 1
    if not entries:
        return None
    return entries[-1]  # oldest = true origin


def compose_at_commit(repo: Path, commit: str, build_id: str) -> dict | None:
    relpath = f"builds/{build_id}/docker-compose.yaml"
    content = run(repo, ["git", "show", f"{commit}:{relpath}"])
    if not content.strip():
        return None
    import yaml
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        return None
    svc = (data.get("services") or {}).get(build_id)
    if svc is None:
        return None
    cmd = svc.get("command")
    cmd_str = cmd if isinstance(cmd, str) else (" ".join(cmd) if cmd else None)
    env = svc.get("environment")
    env_list = None
    if isinstance(env, dict):
        env_list = [f"{k}={v}" for k, v in env.items()]
    elif isinstance(env, list):
        env_list = env
    return {
        "image": svc.get("image"),
        "cmd": cmd_str,
        "env": env_list,
        "devices": svc.get("devices"),
        "group_add": svc.get("group_add"),
        "mem_limit": svc.get("mem_limit"),
    }


def try_repo(repo: Path, repo_label: str, basename: str) -> dict | None:
    origin = find_origin(repo, basename)
    if origin is None:
        return None
    origin_commit, origin_path = origin
    # build_id is the directory right after "builds/"
    parts = origin_path.split("/")
    if "builds" not in parts:
        return None
    build_id = parts[parts.index("builds") + 1]

    parent = run(repo, ["git", "rev-parse", f"{origin_commit}^"]).strip()
    if not parent:
        return None

    compose_info = compose_at_commit(repo, parent, build_id)
    source_commit = parent
    if compose_info is None:
        # build + bench added in the same commit - fall back to the origin itself
        compose_info = compose_at_commit(repo, origin_commit, build_id)
        source_commit = origin_commit
    if compose_info is None:
        return None

    return {
        "reconstructed": True,
        "source": (
            f"git archaeology ({repo_label}) - builds/{build_id}/docker-compose.yaml "
            f"as committed at {source_commit} (the commit immediately preceding "
            "this benchmark result's own commit, i.e. the orchestrator's HEAD at "
            "run time). NOT a live docker inspect - reflects the compose file's "
            "declared command/image/env, not the resolved runtime state (env "
            "expansion, exact image digest pulled at the time)."
        ),
        "build_repo_commit": source_commit,
        "compose": compose_info,
    }


def main():
    json_files = sorted(THIS_REPO.glob("builds/*/benchmarks/llm-inference-bench/*.json"))
    updated = 0
    skipped_has_data = 0
    skipped_not_found = 0

    for path in json_files:
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue

        if data.get("target_launch_config") is not None:
            skipped_has_data += 1
            continue

        basename = path.name
        tlc = try_repo(OLD_REPO, "local-ai-machine (pre-extraction)", basename)
        if tlc is None:
            tlc = try_repo(THIS_REPO, "strix-halo-r9700-llm-builds", basename)

        if tlc is None:
            skipped_not_found += 1
            print(f"SKIP (no history found in either repo): {path.relative_to(THIS_REPO)}")
            continue

        data["target_launch_config"] = tlc
        data.setdefault("server_props", None)
        data.setdefault("bench_tool_commit", None)
        path.write_text(json.dumps(data, indent=2) + "\n")
        updated += 1
        print(f"OK: {path.relative_to(THIS_REPO)} <- {tlc['build_repo_commit'][:8]} ({tlc['source'].split(' - ')[0]})")

    print()
    print(f"updated={updated} skipped_has_data={skipped_has_data} "
          f"skipped_not_found={skipped_not_found} total={len(json_files)}")


if __name__ == "__main__":
    main()
