#!/usr/bin/env python3
"""Headless sweep watchdog for llm-inference-bench.

Self-heals a weekend benchmark sweep so it reaches a terminal state without
manual intervention:

  * Container down  -> `docker compose up -d llm-inference-bench`, then
    re-queue any run that was mid-flight when it died (worker only advances
    "queued" runs; a run persisted as "running" is orphaned forever).
  * Worker wedged   -> queued work remains but the most-recently-active run
    log is stale past STALE_S (30 min, safely above the 20-min health-wait
    silence). Restart the container and re-queue the stuck run's builds.
  * Sweep complete  -> no queued runs and no run with a fresh activity log;
    write a summary to the watchdog log and exit.

State source of truth is the orchestrator queue (builds/.orchestrator/queue.json
via the /queue endpoint). Activity logs live in builds/.orchestrator/runs/<id>.log
and are written at every stage marker and every 60s bench heartbeat, so log mtime
is a reliable liveness signal.

Duplicate queue entries are explicitly OK (orchestrator runs are idempotent per
build) — re-queue is always safe.

Usage: python3 watchdog.py [--once]
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "http://localhost:8092"
# These three paths are NOT the same checkout. The llm-inference-bench
# SERVICE DEFINITION (docker compose up/restart target) lives in
# local-ai-machine's own docker-compose.yml, at that repo's checkout on
# the box — this repo only supplies the published image and the code,
# not the compose service itself. Runtime queue/log state
# (builds/.orchestrator/...) lives under the SEPARATE, dedicated bench
# checkout this script's own code operates against, hard-reset to
# origin/main before every run (see that compose service's own volume
# comment in local-ai-machine's docker-compose.yml).
DOCKER_DIR = Path("/var/lib/git-checkouts/local-ai-machine/docker")
CONTAINER = "llm-inference-bench"
RUNS_LOG_DIR = Path("/var/lib/git-checkouts/strix-halo-r9700-llm-builds/builds/.orchestrator/runs")
WATCHDOG_LOG = Path("/var/lib/git-checkouts/strix-halo-r9700-llm-builds/builds/.orchestrator/watchdog.log")

POLL_S = 60
STALE_S = 30 * 60            # run log older than this with queued work pending -> wedged
FRESH_S = 2 * 3600           # "running" run with log touched within this window = was mid-flight
RESTART_COOLDOWN_S = 5 * 60  # don't restart-loop faster than this


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str):
    line = f"[{utcnow()}] {msg}"
    print(line, flush=True)
    with open(WATCHDOG_LOG, "a") as f:
        f.write(line + "\n")


def api(path: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def container_up() -> bool:
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=20
    )
    return CONTAINER in out.stdout.split()


def compose_up():
    log("container down - starting llm-inference-bench")
    subprocess.run(
        ["docker", "compose", "up", "-d", CONTAINER],
        cwd=str(DOCKER_DIR), check=True, timeout=120,
    )
    time.sleep(15)


def compose_restart():
    log("restarting llm-inference-bench")
    subprocess.run(
        ["docker", "compose", "restart", CONTAINER],
        cwd=str(DOCKER_DIR), check=True, timeout=120,
    )
    time.sleep(15)


def run_log_mtime(run_id: str) -> float:
    p = RUNS_LOG_DIR / f"{run_id}.log"
    return p.stat().st_mtime if p.exists() else 0.0


def requeue_builds(run_ids: list, reason: str):
    """POST a fresh single-build run per build in the orphaned runs."""
    for rid in run_ids:
        try:
            run = api(f"/runs/{rid}")
        except Exception as e:
            log(f"requeue: could not read run {rid}: {e}")
            continue
        builds = run.get("builds", [])
        try:
            resp = api("/runs", method="POST", body={"runs": [[b] for b in builds]})
            new_ids = [r["id"] for r in resp.get("created", [])]
            log(f"requeued {builds} (from run {rid}) as runs {new_ids} ({reason})")
        except Exception as e:
            log(f"requeue FAILED for {builds} (from run {rid}): {e}")


def close_runs(run_ids: list, reason: str):
    """Force abandoned stale-running runs to a terminal (failed) state via the
    orchestrator's /runs/{id}/close endpoint, so the sweep ends with no
    running leftovers. The worker never advances a run persisted as 'running'
    after a restart, so a non-active stale-running run can only be garbage."""
    for rid in run_ids:
        try:
            api(f"/runs/{rid}/close", method="POST", body={"status": "failed", "error": reason})
            log(f"closed stale-running orphan {rid} ({reason})")
        except Exception as e:
            log(f"close run {rid} FAILED: {e}")


def sweep_state(runs):
    running = [r for r in runs if r["status"] == "running"]
    queued = [r for r in runs if r["status"] == "queued"]
    done = [r for r in runs if r["status"] == "done"]
    failed = [r for r in runs if r["status"] == "failed"]
    # Most-recently-active run log = worker's current heartbeat. Other runs
    # left 'running' are orphans the worker can never resume (it only advances
    # 'queued' state) — they are garbage once stale.
    active = max(running, key=lambda r: run_log_mtime(r["id"])) if running else None
    now = time.time()
    orphans = [r for r in running if active is not None and r["id"] != active["id"]
               and now - run_log_mtime(r["id"]) > STALE_S]
    return running, queued, done, failed, active, orphans


def main(once: bool):
    try:
        total = len(api("/queue").get("runs", []))
    except Exception:
        total = "?"
    log(f"watchdog start: {total} total runs")
    last_restart = 0.0
    runs = []
    first = True
    while True:
        if not first:
            time.sleep(POLL_S)
        first = False
        now = time.time()

        try:
            runs = api("/queue").get("runs", [])
        except Exception as e:
            log(f"API unreachable: {e}")
            if not container_up():
                compose_up()
                # Re-queue runs that were mid-flight when the container died,
                # then close the originals so they can't linger as running.
                req = [r["id"] for r in runs if r["status"] == "running"
                       and now - run_log_mtime(r["id"]) < FRESH_S]
                if req:
                    requeue_builds(req, "post-crash")
                    close_runs(req, "requeued after container crash")
            continue

        running, queued, done, failed, active, orphans = sweep_state(runs)
        log(f"progress: queued={len(queued)} running={len(running)} done={len(done)} failed={len(failed)}")

        if not container_up():
            compose_up()
            req = [r["id"] for r in running if now - run_log_mtime(r["id"]) < FRESH_S]
            if req:
                requeue_builds(req, "post-crash")
                close_runs(req, "requeued after container crash")
            continue

        # Stale-running runs the worker abandoned (it only advances 'queued'
        # state) are garbage: close them so the sweep ends terminal, with no
        # leftover 'running' entries waiting on a requeue that never comes.
        if orphans:
            close_runs([r["id"] for r in orphans], "stale-running orphan (worker only advances queued runs)")
            running = [r for r in running if r["id"] == active["id"]]

        # A stale 'running' run with NO queued work is also an orphan: the
        # worker can only hold a run open while executing it, and with nothing
        # queued there is nothing for it to be wedged on. Close it so the
        # sweep ends with zero running leftovers.
        if active is not None and not queued and now - run_log_mtime(active["id"]) > STALE_S:
            close_runs([active["id"]], "stale-running with no queued work (worker never resumes it)")
            active = None
            running = []

        if queued and active is not None and now - run_log_mtime(active["id"]) > STALE_S:
            log(f"worker wedged: run {active['id']} log stale "
                f"{int(now - run_log_mtime(active['id']))}s, {len(queued)} queued")
            if now - last_restart < RESTART_COOLDOWN_S:
                log("cooldown in effect - requeueing without restart")
                requeue_builds([active["id"]], "wedged")
                continue
            last_restart = now
            compose_restart()
            requeue_builds([active["id"]], "wedged")
            continue

        # Completion: nothing queued and no run with a live heartbeat.
        live = [r["id"] for r in running if now - run_log_mtime(r["id"]) < STALE_S]
        if not queued and not live:
            log(f"SWEEP COMPLETE: done={len(done)} failed={len(failed)} "
                f"stale-running-leftover={len(running)}")
            return

        if once:
            return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single poll, then exit")
    args = ap.parse_args()
    main(args.once)
