"""Per-build docker-compose.yaml parsing + docker CLI helpers.

Each build under builds/<id>/ is its own standalone compose project (one
service, its own docker-compose.yaml) - the same model modelctl uses, not
a single shared compose file. The field-extraction logic below (port,
served_model_name, always_up) is a straight port of the original single-
shared-file parser; only the *source* of what gets iterated changed.

The always_up field is still parsed and still means something (see
orchestrator.py's _wait_all_healthy — an always-up run TARGET is confirmed
reachable rather than cycled with `compose up`), but it no longer decides
which OTHER services get stopped for GPU exclusivity - see orchestrator.py's
_establish_exclusivity/_is_model_build for that decision (any real model
build, always-up or not, sharing the run's GPU).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from . import log

ALWAYS_UP_LABEL = "com.local-ai-machine.always-up"


def run(cmd, cwd=None, check=True, timeout=None, text=True, env=None):
    """Run a command, log it, return CompletedProcess. Mirrors the old
    orchestrator's run() so behavior stays familiar and debuggable."""
    printable = cmd if isinstance(cmd, str) else " ".join(cmd)
    log.line(f"$ {printable}")
    kwargs = dict(cwd=cwd, timeout=timeout, text=text, env=env)
    if text:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result = subprocess.run(cmd, shell=isinstance(cmd, str), **kwargs)
    if result.stdout:
        log.line(result.stdout[-4000:])
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {printable}")
    return result


def project_name_for(build_id: str) -> str:
    """Compose project names are far stricter than build directory names:
    only lowercase alphanumerics, hyphens, and underscores, must start
    with a letter or digit. Build ids commonly carry version-number
    periods (e.g. "qwen3.8-27b-..."), which `docker compose -p` rejects
    outright — confirmed live. Same transform as modelctl's own
    project_name_for."""
    return build_id.replace(".", "_")


def _parse_service(svc: dict) -> dict:
    port = None
    for p in svc.get("ports") or []:
        parts = str(p).split(":")
        if len(parts) >= 2 and parts[0] == "127.0.0.1":
            try:
                port = int(parts[1])
            except ValueError:
                pass
            break
    served_name = None
    cmd = svc.get("command")
    if cmd:
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        tokens = cmd_str.split()
        for i, token in enumerate(tokens):
            if token == "--served-model-name" and i + 1 < len(tokens):
                served_name = tokens[i + 1]
                break
    labels = svc.get("labels") or {}
    if isinstance(labels, dict):
        always_up = labels.get(ALWAYS_UP_LABEL) == "true"
    else:
        always_up = f"{ALWAYS_UP_LABEL}=true" in (labels or [])
    return {"port": port, "served_model_name": served_name, "always_up": always_up}


def load_all_build_services(builds_dir: Path) -> dict:
    """Scan builds_dir/*/docker-compose.yaml -> {build_id: {port,
    served_model_name, always_up}}, one entry per build directory that
    actually has a compose file. build_id is the directory name, which is
    also the service name inside its own compose file (confirmed 1:1
    across every build, same invariant modelctl relies on)."""
    services = {}
    for build_dir in sorted(builds_dir.iterdir()):
        compose_path = build_dir / "docker-compose.yaml"
        if not compose_path.is_file():
            continue
        with open(compose_path) as f:
            compose = yaml.safe_load(f)
        svc = (compose.get("services") or {}).get(build_dir.name)
        if svc is None:
            continue
        services[build_dir.name] = _parse_service(svc)
    return services


def compose(build_id: str, args, builds_dir: Path, check=True, timeout=None, extra_compose_files=None):
    """docker compose <args> against one build's own standalone compose
    project - never a shared file, never a shared project name. Same -p
    isolation modelctl uses (see its own comment for why this is
    mandatory, not cosmetic): every build's compose file declares `name:
    docker`, matching the always-up base stack's own compose project
    name, so without an explicit override every build and the base stack
    would share one Compose project and its default network.

    extra_compose_files: optional list of additional `-f` files layered on
    top of the build's own compose file (later files win on conflicting
    keys, standard Compose merge semantics). Used by the orchestrator to
    apply benchmark-only overrides (e.g. -sps 0 for spec-decode targets,
    see orchestrator.py's _write_sps_override) without ever touching the
    build's own committed docker-compose.yaml - a plain `docker compose up`
    or modelctl launch never sees these files and is unaffected.
    """
    build_dir = builds_dir / build_id
    compose_file = build_dir / "docker-compose.yaml"
    f_args = ["-f", str(compose_file)]
    for extra in (extra_compose_files or []):
        f_args += ["-f", str(extra)]
    return run(
        ["docker", "compose", "-p", project_name_for(build_id), *f_args, *args],
        cwd=str(build_dir),
        check=check,
        timeout=timeout,
    )
