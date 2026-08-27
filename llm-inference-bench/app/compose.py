"""docker-compose.yml parsing + docker CLI helpers.

The parser is a deliberate port of scripts/benchmark_orchestrator.py's
_load_compose_services() (same field semantics, same label semantics).

The always_up field is still parsed and still means something (see
orchestrator.py's _wait_all_healthy — an always-up run TARGET is confirmed
reachable rather than cycled with `compose up`), but as of 2026-08-23 it no
longer decides which OTHER services get stopped for GPU exclusivity - see
orchestrator.py's _establish_exclusivity/_is_model_build for that decision
(any real model build, always-up or not, sharing the run's GPU).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from . import log

# Compose project name on the box. The existing orchestrator runs from
# ~/local-ai-machine/docker with no explicit -p, so the inferred project
# name is the directory basename "docker". Our checkout lives at
# /bench/docker, whose basename is also "docker" — same inference — but we
# pass -p docker explicitly anyway so a future path change can't silently
# fork the project and make `compose up -d <svc>` operate on the wrong set
# of containers.
PROJECT_NAME = "docker"

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


def load_compose_services(compose_path: Path) -> dict:
    """Parse docker-compose.yml -> {service_name: {port, served_model_name,
    always_up}}. Port is the host-side int of the first 127.0.0.1 mapping
    (matches the old orchestrator exactly)."""
    with open(compose_path) as f:
        compose = yaml.safe_load(f)
    services = {}
    for name, svc in (compose.get("services") or {}).items():
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
        services[name] = {"port": port, "served_model_name": served_name, "always_up": always_up}
    return services


def compose(args, docker_dir: Path, check=True, timeout=None):
    """docker compose <args> against the checkout's compose file.

    -f is passed explicitly, never implied from cwd. Compose 2.26.1 (the
    version baked into the bench image) otherwise discovers the project's
    config files from running containers' labels — and the shared "docker"
    project mixes containers created from TWO different compose files (the
    always-up stack launched by host compose 5.3.1 from
    /var/lib/git-checkouts/local-ai-machine/docker/docker-compose.yml, and
    the bench services created from this checkout). The host path is
    invisible inside the container, so label-driven discovery makes every
    `stop` fail with "could not find <service>: not found" as soon as a
    bench-created container is up. Pinning -f makes the bench checkout the
    sole source of truth for the project model.
    """
    compose_file = docker_dir / "docker-compose.yml"
    return run(
        ["docker", "compose", "-p", PROJECT_NAME, "-f", str(compose_file), *args],
        cwd=str(docker_dir),
        check=check,
        timeout=timeout,
    )
