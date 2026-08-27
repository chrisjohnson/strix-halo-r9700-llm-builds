"""Benchmark queue + run lifecycle for the llm-inference-bench container.

One worker thread processes the queue serially (one run at a time). Queue and
per-run state persist to builds/.orchestrator/queue.json inside the mounted
checkout (gitignored, see root .gitignore) so the orchestrator's own
container restart resumes pending runs instead of losing them.

Run lifecycle (per the M-101 refined design):
  1. hard-reset the mounted checkout to origin/main (compose defs + build.yaml
     are current before anything else touches the box's model services)
  2. stop every OTHER model build on the SAME GPU as this run's targets,
     except the targets themselves (GPU-scoped since 2026-08-20, M-125
     dual-GPU follow-up — a run's exclusivity no longer touches standing
     services on a GPU it never uses; see _establish_exclusivity). As of
     2026-08-23 (Chris's directive) this includes always-up standing
     models too, not just non-always-up ones - a benchmark taking a GPU
     is expected to have it to itself, full stop; always-up INFRA
     (litellm, db, monitoring, dsh, ...) is unaffected either way.
  3. bring up targets via named services, wait for health
  4. per build, serially: run llm_decode_bench.py, raw JSON + stdout log saved
     under builds/<build>/benchmarks/llm-inference-bench/
  5. on success: git pull --rebase + add + commit + push straight to main
  6. leave targets up; every other same-GPU model build stays stopped -
     deliberately NOT restored (Chris: "It doesn't even need to restore
     them afterward, I didn't say it should do that") - each standing
     model's own restart:always policy is what's expected to matter,
     and only for crashes/reboots, not a benchmark's deliberate stop

Failure modes adopted from the existing stack (OPERATIONS.md +
benchmark_orchestrator.py): hard-fail on empty/no-completions results (never
trust bogus data); health-wait before every bench; bounded-but-generous whole
build timeout; no service cycling mid-run (2026-07-29 full-system hang);
crash = restart once + re-run once, second crash = docker logs + fail.
Download pausing is explicitly out of scope for v1 (container can't
sudo -n systemctl) and documented in the card.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import yaml

from . import compose as dc
from . import log
from .config import Config

STATE_VERSION = 1


def utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_for_filename() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _bench_key() -> str:
    return "llm-inference-bench"


class Orchestrator:
    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()
        self._worker = None
        self._state = {"version": STATE_VERSION, "next_id": 1, "runs": {}}
        self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self):
        path = self.config.state_path
        if path.exists():
            try:
                data = json.loads(path.read_text())
                if data.get("version") == STATE_VERSION:
                    self._state = data
            except (json.JSONDecodeError, OSError) as e:
                log.line(f"WARNING: could not load queue state from {path}: {e}; starting fresh")

    def _save_state(self):
        path = self.config.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._state, indent=2))
        os.replace(tmp, path)

    # ------------------------------------------------------------------
    # Queue API (thread-safe)
    # ------------------------------------------------------------------

    def _next_id(self):
        run_id = str(self._state["next_id"])
        self._state["next_id"] += 1
        return run_id

    def enqueue(self, builds: list) -> dict:
        """Validate + enqueue one run. Rejects unknown service names and
        always-up infra services (nothing to benchmark behind a generic
        gateway), so a fat-fingered POST can never stop real infra."""
        services = self.services()
        unknown = [b for b in builds if b not in services]
        if unknown:
            raise ValueError(f"Unknown build/service names: {unknown}")
        infra = [b for b in builds if services[b]["always_up"] and not self._always_up_benchmarkable(b)]
        if infra:
            raise ValueError(f"Not benchmarkable (always-up infra): {infra}")
        with self._lock:
            run_id = self._next_id()
            run = {
                "id": run_id,
                "status": "queued",
                "builds": list(builds),
                "created_at": utcnow_iso(),
                "started_at": None,
                "finished_at": None,
                "error": None,
                "per_build": {
                    b: {
                        "status": "pending",
                        "error": None,
                        "raw_json": None,
                        "stdout_log": None,
                        "crash_log": None,
                        "attempts": 0,
                    }
                    for b in builds
                },
            }
            self._state["runs"][run_id] = run
            self._save_state()
        return run

    def list_runs(self):
        with self._lock:
            return [self._state["runs"][r] for r in sorted(self._state["runs"], key=int)]

    def get_run(self, run_id: str):
        with self._lock:
            return self._state["runs"].get(run_id)

    def _update_run(self, run_id: str, **fields):
        with self._lock:
            run = self._state["runs"][run_id]
            run.update(fields)
            self._save_state()

    def _update_build(self, run_id: str, build: str, **fields):
        with self._lock:
            run = self._state["runs"][run_id]
            run["per_build"][build].update(fields)
            self._save_state()

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    def start(self):
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._worker_loop, name="bench-worker", daemon=True)
        self._worker.start()

    def _worker_loop(self):
        while True:
            run = self._next_queued_run()
            if run is None:
                time.sleep(5)
                continue
            self._execute_run(run["id"])

    def _next_queued_run(self) -> dict | None:
        with self._lock:
            for run_id in sorted(self._state["runs"], key=int):
                run = self._state["runs"][run_id]
                if run["status"] == "queued":
                    return dict(run)
        return None

    # ------------------------------------------------------------------
    # Compose surface (re-read each run — reset --hard may have changed it)
    # ------------------------------------------------------------------

    def services(self) -> dict:
        return dc.load_all_build_services(self.config.checkout_dir / "builds")

    def _always_up_benchmarkable(self, build: str) -> bool:
        # Always-up services that are benchmark targets: they carry a
        # build.yaml (a catalog entry) and are benchmarked against their
        # running instance via the OpenAI-compatible /v1 API without
        # stop/start — same as ollama. Always-up infra (litellm, db,
        # monitoring, web UIs) has no build.yaml and is not a target.
        return (self.config.checkout_dir / "builds" / build / "build.yaml").exists()

    # DEFAULT_TARGET_GPU mirrors scripts/generate_interactive_dashboard.py's
    # own constant/reasoning exactly: every build.yaml predating the R9700
    # (2026-08-20) has no target_gpu field at all, and every one of those
    # builds is strix-apu in reality (vLLM builds are architecture-locked to
    # gfx1151, everything else predates the second GPU existing) - so
    # defaulting missing/unreadable target_gpu to strix-apu is a real fact
    # about this box's current builds, not a guess.
    DEFAULT_TARGET_GPU = "strix-apu"

    def _target_gpu(self, build: str) -> str:
        """Which GPU (catalog/hardware.yaml id) this build targets, read
        from its own builds/<build>/build.yaml (derived.target_gpu) - the
        same file _always_up_benchmarkable already reads to confirm a
        build.yaml exists at all. Falls back to DEFAULT_TARGET_GPU for
        infra services with no build.yaml (never called for those - see
        _establish_exclusivity, which only calls this for compose services
        that ARE builds) and for any build.yaml missing the field."""
        path = self.config.checkout_dir / "builds" / build / "build.yaml"
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            return self.DEFAULT_TARGET_GPU
        return (data.get("derived") or {}).get("target_gpu") or self.DEFAULT_TARGET_GPU

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def activity_log_path(self, run_id: str) -> Path:
        """Per-run activity log: every worker stage marker, echoed command
        and subprocess line the run produces, streamed live to the UI. Lives
        under the gitignored .orchestrator dir so it is never committed."""
        return self.config.checkout_dir / "builds" / ".orchestrator" / "runs" / f"{run_id}.log"

    def run_terminal(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        return run is not None and run["status"] in ("done", "failed")

    def close_run(self, run_id: str, status: str = "failed", error: str | None = None) -> dict | None:
        """Force a stuck (stale-running / orphaned) run to a terminal state.
        Used by the watchdog to close runs the worker abandoned mid-flight
        (container crash before requeue, or a leftover that lost its liveness
        log). Marks every non-terminal per-build as failed so the queue
        reflects reality. No-op for already-terminal runs."""
        with self._lock:
            run = self._state["runs"].get(run_id)
            if run is None:
                return None
            if run["status"] in ("done", "failed"):
                return dict(run)
            if status not in ("done", "failed"):
                raise ValueError(f"invalid terminal status: {status}")
            reason = error or f"run closed by watchdog (was {run['status']}, never reached a terminal state)"
            run["status"] = status
            run["error"] = reason
            run["finished_at"] = utcnow_iso()
            for build, per_build in run.get("per_build", {}).items():
                if per_build["status"] not in ("done", "failed"):
                    per_build["status"] = "failed"
                    per_build["error"] = reason
            self._save_state()
            return dict(run)

    def _execute_run(self, run_id: str):
        self._update_run(run_id, status="running", started_at=utcnow_iso())
        log_path = self.activity_log_path(run_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        targets: list = []
        services: dict = {}
        try:
            with open(log_path, "w") as sink:
                log.set_sink(sink)
                try:
                    self._git_sync()
                    services = self.services()
                    targets = list(self.get_run(run_id)["builds"])
                    unknown = [b for b in targets if b not in services]
                    if unknown:
                        raise RuntimeError(f"Unknown build/service names after git sync: {unknown}")

                    # Known-broken builds (build.yaml status: BROKEN with a
                    # recorded reason) are failed fast — no compose up, no
                    # 20-min health-wait burn on a build the catalog already
                    # proved dead. Remaining targets run as normal.
                    targets = self._fail_known_broken(run_id, targets)
                    if not targets:
                        log.line("[run] all targets known-broken — nothing to benchmark")
                        self._update_run(run_id, status="done", finished_at=utcnow_iso())
                        return

                    self._establish_exclusivity(targets, services)
                    self._wait_all_healthy(targets, services)

                    for build in targets:
                        self._benchmark_build(run_id, build, services)

                    self._update_run(run_id, status="done", finished_at=utcnow_iso())
                finally:
                    log.clear_sink()
        except Exception as e:  # noqa: BLE001
            log.line(f"[run {run_id}] FAILED: {e}")
            # Launch-phase failures (exclusivity stop, health-wait timeout) abort
            # the run before _benchmark_build ever marks a per-build status. Mark
            # every non-terminal target failed so the UI/queue reflects reality,
            # and capture the container logs that explain WHY it didn't launch —
            # the previous behavior recorded neither.
            self._fail_pending_targets(run_id, targets, services, e)
            self._update_run(run_id, status="failed", error=str(e), finished_at=utcnow_iso())

    def _fail_pending_targets(self, run_id: str, targets: list, services: dict, error: Exception):
        """Mark every target that didn't reach a terminal state as failed with
        the run error, capturing docker logs as a launch log where available."""
        run = self.get_run(run_id)
        for build in targets:
            per_build = (run.get("per_build") or {}).get(build)
            if per_build is None or per_build["status"] in ("done", "failed"):
                continue
            fields = {"status": "failed", "error": str(error)}
            try:
                launch_log = self._capture_launch_log(build, services.get(build, {}))
                if launch_log is not None:
                    fields["crash_log"] = str(launch_log.relative_to(self.config.checkout_dir))
                    # Classify the failure from the captured log so the WHY is
                    # durable and greppable, not just "health-wait timeout".
                    kind, detail = self._classify_launch_failure(
                        launch_log.read_text(errors="replace"), str(error)
                    )
                    fields["failure_kind"] = kind
                    fields["error"] = f"{str(error)} — [{kind}] {detail}"
                    # Commit the classified failure record alongside the raw log.
                    try:
                        fail_md = launch_log.with_name(f"{launch_log.stem}-failure.md")
                        fail_md.write_text(self._failure_markdown(build, kind, detail, launch_log))
                        self._commit_and_push(
                            [launch_log, fail_md],
                            f"bench: {build} llm-inference-bench launch-failure {kind}",
                        )
                    except Exception as md_err:  # noqa: BLE001
                        log.line(f"[run {run_id}] could not commit failure record for {build}: {md_err}")
            except Exception as capture_err:  # noqa: BLE001
                # A log-capture or commit failure must never mask the primary
                # run failure or break the pending-target marking.
                log.line(f"[run {run_id}] could not capture launch log for {build}: {capture_err}")
            self._update_build(run_id, build, **fields)

    # Failure signatures: (kind, regexes). Ordered — first match wins.
    LAUNCH_FAILURE_SIGNATURES = [
        ("oom",
         [r"out of memory", r"ErrorOutOfDeviceMemory", r"Not enough memory for command submission",
          r"cudaMalloc failed", r"CUDA error.*out of memory"]),
        ("device-lost", [r"vk::DeviceLostError", r"device lost"]),
        ("nvfp4-unsupported", [r"NvFp4", r"NVFP4", r"No NvFp4 MoE backend"]),
        ("missing-model-file", [r"No such file or directory", r"FileNotFoundError", r"does not exist",
                                r"Failed to open.*\.gguf", r"not found.*\.gguf"]),
        ("import-error", [r"ImportError", r"ModuleNotFoundError", r"No module named"]),
        ("kv-cap", [r"max_num_seqs.*exceeds.*cache blocks", r"not enough cache"]),
        ("server-up-probe-mismatch", [r"listening on http", r"Application startup complete"]),
    ]

    @classmethod
    def _classify_launch_failure(cls, log_text: str, error_text: str) -> tuple[str, str]:
        """Best-effort classification of a launch failure from the container
        log + the run error. Returns (kind, detail) — kind defaults to
        'health-wait' (server never became reachable)."""
        if not log_text:
            return "health-wait", "no container log captured (compose up failed before launch?)"
        for kind, patterns in cls.LAUNCH_FAILURE_SIGNATURES:
            for pat in patterns:
                m = re.search(pat, log_text, re.IGNORECASE)
                if m:
                    line = next((ln for ln in log_text.splitlines() if pat.lower() in ln.lower() and ln.strip()), "")
                    snippet = " ".join(line.split())[:200] if line else m.group(0)
                    return kind, snippet
        return "health-wait", f"server never reachable during health-wait: {str(error_text)[:160]}"

    @staticmethod
    def _failure_markdown(build: str, kind: str, detail: str, launch_log) -> str:
        rel = "/".join(str(launch_log).split("/")[-3:])
        return (
            f"# Launch failure — {build}\n\n"
            f"- **time**: {utcnow_iso()}\n"
            f"- **kind**: {kind}\n"
            f"- **detail**: {detail}\n"
            f"- **raw log**: `{rel}`\n\n"
            f"Classified automatically by the llm-inference-bench orchestrator "
            f"(M-106 failure-diagnosis).\n"
        )

    def _fail_known_broken(self, run_id: str, targets: list) -> list:
        """Fail-fast any target whose build.yaml status is known-failed
        (BROKEN or TESTED_NOT_VIABLE — the catalog already proved them dead
        or not-viable), using the recorded reason instead of spending a
        health-wait. Returns the surviving (worth-running) list."""
        survivors = []
        for build in targets:
            reason = self._build_broken_reason(build)
            if reason is None:
                survivors.append(build)
                continue
            log.line(f"[run {run_id}] {build} known-failed (build.yaml) — failing fast: {reason}")
            self._update_build(
                run_id, build,
                status="failed",
                error=f"known-failed (build.yaml status): {reason}",
            )
        return survivors

    def _build_broken_reason(self, build: str) -> str | None:
        """Read builds/<build>/build.yaml; return the human reason if the
        status is known-failed (BROKEN or TESTED_NOT_VIABLE, case-
        insensitive), else None. Missing/unparseable file or missing status =
        not known-failed (run it normally)."""
        build_yaml = self.config.checkout_dir / "builds" / build / "build.yaml"
        if not build_yaml.exists():
            return None
        try:
            data = yaml.safe_load(build_yaml.read_text()) or {}
        except (yaml.YAMLError, OSError) as e:
            log.line(f"[bench] WARNING: could not parse {build_yaml}: {e}; treating as not-broken")
            return None
        status = str(data.get("status") or "").strip().upper()
        if status not in ("BROKEN", "TESTED_NOT_VIABLE"):
            return None
        notes = str(
            (data.get("derived") or {}).get("notes")
            or data.get("notes")
            or "no reason recorded"
        ).strip()
        return notes

    def _capture_launch_log(self, build: str, info: dict) -> Path | None:
        """Save the container's tail logs explaining why it failed to launch.
        Returns the saved path, or None if the container never existed or never
        wrote anything (e.g. compose up failed before a container was created)."""
        exists = dc.run(["docker", "ps", "-a", "--filter", f"name=^{build}$", "--format", "{{.Names}}"], check=False).stdout.strip()
        if not exists:
            return None
        out_dir = self.config.checkout_dir / "builds" / build / "benchmarks" / _bench_key()
        out_dir.mkdir(parents=True, exist_ok=True)
        raw = dc.run(["docker", "logs", build, "--tail", "300"], check=False).stdout
        if not raw.strip():
            return None
        launch_log = out_dir / f"{ts_for_filename()}-launch.log"
        launch_log.write_text(raw)
        return launch_log

    def _git_sync(self):
        checkout = self.config.checkout_dir
        env = self._git_env()
        log.line("[git] fetching + hard resetting checkout to origin/main ...")
        dc.run(["git", "fetch", "origin", self.config.git_branch], cwd=str(checkout), env=env, timeout=300)
        dc.run(["git", "reset", "--hard", f"origin/{self.config.git_branch}"], cwd=str(checkout), env=env)

    def _git_env(self):
        env = dict(os.environ)
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {self.config.deploy_key} -o IdentitiesOnly=yes "
            f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={self.config.known_hosts}"
        )
        env["GIT_AUTHOR_NAME"] = self.config.git_author_name
        env["GIT_AUTHOR_EMAIL"] = self.config.git_author_email
        env["GIT_COMMITTER_NAME"] = self.config.git_author_name
        env["GIT_COMMITTER_EMAIL"] = self.config.git_author_email
        return env

    def _is_model_build(self, name: str) -> bool:
        """True if this compose service is a real model build (has
        builds/<name>/build.yaml) - the same has-a-build.yaml test
        _always_up_benchmarkable already uses to separate real models from
        always-up INFRA (litellm, db, monitoring, dsh, ...), which must
        never be stopped regardless of GPU. A model build's own always-up
        label is no longer relevant to whether it's stoppable - see
        _establish_exclusivity."""
        return (self.config.checkout_dir / "builds" / name / "build.yaml").exists()

    def _establish_exclusivity(self, targets: list, services: dict):
        """Stop every OTHER model build ON THE SAME GPU(S) as this run's
        targets, except the targets themselves, freeing that GPU's budget.
        GPU-scoped since 2026-08-20 (M-125 dual-GPU follow-up) — a run's
        exclusivity doesn't touch standing services on a GPU it never
        uses.

        2026-08-23 (Chris's directive): previously exempted always-up
        services from this entirely, only ever stopping non-always-up
        ones. That exemption caused a real, repeated incident: an
        always-up standing model (qwen3.8-27b-q6kl) sharing the r9700
        with a benchmark target wasn't stopped, silently contending for
        VRAM instead of being freed — real requests degraded to 6-8
        tok/s, ~45 MiB free out of ~30 GiB. Chris: "If I am triggering a
        benchmark, I want it to manage the models on my machine. It's
        definitely not desirable that I leave laguna and ornith running
        while ALSO trying to benchmark another model" (both are
        always-up and, like q6kl, tuned to use ~100% of their GPU's
        capacity on their own). Always-up INFRA is unaffected — the
        has-build.yaml test in _is_model_build is what actually draws
        that line, not the always-up label, which no longer factors in
        at all. Deliberately NOT restored afterward (Chris: "It doesn't
        even need to restore them afterward, I didn't say it should do
        that") - each standing model's own restart:always policy is
        what's expected to matter here, and only for crashes/reboots,
        not a benchmark's deliberate stop.

        Containers are stopped ONE AT A TIME (check=False): a single hung
        container (GPU process stuck in an unkillable state — see the
        nemotron incident, 2026-08-08) must not abort the whole run's
        exclusivity step. Each failed stop is logged and skipped; the bench
        proceeds and the hung container surfaces as a health/OOM failure on
        the target instead of killing every queued run in one batch."""
        target_gpus = {self._target_gpu(t) for t in targets}
        log.line(f"[exclusivity] this run's targets are on GPU(s): {sorted(target_gpus)}")
        stoppable = [
            name for name in services
            if name not in targets and self._is_model_build(name) and self._target_gpu(name) in target_gpus
        ]
        if not stoppable:
            log.line("[exclusivity] no other model builds on this GPU — nothing to stop")
            return
        log.line(f"[exclusivity] stopping model builds not in this run: {stoppable}")
        hung = []
        for name in stoppable:
            try:
                result = dc.compose(name, ["stop"], self.config.checkout_dir / "builds", check=False, timeout=120)
                if result.returncode != 0:
                    hung.append(name)
                    log.line(f"[exclusivity] WARNING: stop {name} returned {result.returncode}: {result.stdout[-400:]}")
            except subprocess.TimeoutExpired:
                hung.append(name)
                log.line(f"[exclusivity] WARNING: stop {name} timed out (container likely hung)")
        if hung:
            log.line(f"[exclusivity] could not stop {len(hung)} services (hung): {hung}")

    def _wait_all_healthy(self, targets: list, services: dict):
        for build in targets:
            info = services[build]
            if info["always_up"]:
                # Always-up targets (ollama) are already up — just confirm healthy.
                log.line(f"[health] {build} is always-up, confirming reachable ...")
                self._wait_healthy(build, info, already_up=True)
            else:
                log.line(f"[health] bringing up {build} ...")
                dc.compose(build, ["up", "-d"], self.config.checkout_dir / "builds", timeout=600)
                self._wait_healthy(build, info, already_up=False)

    def _wait_healthy(self, build: str, info: dict, already_up: bool):
        port = info["port"]
        if port is None:
            raise RuntimeError(f"Service '{build}' has no 127.0.0.1 port mapping — cannot health-check or benchmark")
        deadline = time.time() + self.config.health_wait_s
        while time.time() < deadline:
            if self._probe(port):
                log.line(f"[health] {build} healthy on :{port}")
                return
            time.sleep(10)
        raise RuntimeError(f"Timed out waiting for {build} to become healthy on port {port}")

    @staticmethod
    def _probe(port: int) -> bool:
        # /health first (vLLM, llama-server); fall back to / for servers that
        # only answer at the root (ollama returns "Ollama is running" on /).
        # /v1/models last: OpenAI-compat servers that expose neither health nor
        # root endpoints (ds4-server answers only /v1/models — M-106 run 75).
        for path in ("/health", "/", "/v1/models"):
            result = dc.run(["curl", "-sf", "-o", "/dev/null", "-w", "%{http_code}", f"http://localhost:{port}{path}"], check=False)
            if result.returncode == 0 and result.stdout.strip() == "200":
                return True
        return False

    # ------------------------------------------------------------------
    # Per-build benchmark
    # ------------------------------------------------------------------

    def _benchmark_build(self, run_id: str, build: str, services: dict):
        self._update_build(run_id, build, status="running", attempts=0)
        info = services[build]
        port = info["port"]
        overrides = self._build_overrides(build)
        log.line(f"[bench] {build} on :{port}")

        out_dir = self.config.checkout_dir / "builds" / build / "benchmarks" / _bench_key()
        out_dir.mkdir(parents=True, exist_ok=True)

        raw_json = out_dir / f"{ts_for_filename()}.json"
        stdout_log = out_dir / f"{raw_json.stem}-stdout.log"
        crash_log = out_dir / f"{raw_json.stem}-crash.log"

        bench_cmd = self._bench_command(port, overrides, raw_json)
        timeout_s = int(overrides.get("timeout_s", self.config.build_timeout_s))

        try:
            # Crash handling: if the model container dies mid-bench, restart
            # it once and re-run the benchmark once; a second crash is a hard
            # failure with the container logs saved.
            max_attempts = 2
            for attempt in range(1, max_attempts + 1):
                self._update_build(run_id, build, attempts=attempt)
                crashed = self._run_bench_timed(bench_cmd, stdout_log, build, info, timeout_s)
                if not crashed:
                    break
                if attempt < max_attempts:
                    log.line(f"[bench] {build} crashed during attempt {attempt} — restarting and re-running once")
                    dc.compose(build, ["up", "-d"], self.config.checkout_dir / "builds", timeout=600)
                    self._wait_healthy(build, info, already_up=False)
                else:
                    self._save_crash_log(build, crash_log)
                    self._update_build(run_id, build, status="failed", crash_log=str(crash_log.relative_to(self.config.checkout_dir)))
                    raise RuntimeError(f"{build} crashed twice during benchmark; logs saved to {crash_log.relative_to(self.config.checkout_dir)}")

            self._validate_results(raw_json)
            log.line(f"[bench] {build} complete: {raw_json.relative_to(self.config.checkout_dir)}")
            self._update_build(
                run_id, build, status="done",
                raw_json=str(raw_json.relative_to(self.config.checkout_dir)),
                stdout_log=str(stdout_log.relative_to(self.config.checkout_dir)),
            )
            self._commit_and_push([raw_json, stdout_log], f"bench: {build} llm-inference-bench raw results")
        except Exception as e:  # noqa: BLE001
            fields = {"status": "failed", "error": str(e),
                      "raw_json": str(raw_json.relative_to(self.config.checkout_dir)) if raw_json.exists() else None,
                      "stdout_log": str(stdout_log.relative_to(self.config.checkout_dir)) if stdout_log.exists() else None}
            if crash_log.exists():
                fields["crash_log"] = str(crash_log.relative_to(self.config.checkout_dir))
            self._update_build(run_id, build, **fields)
            # Commit whatever the failed bench produced so the evidence is in
            # git history, not stranded as untracked files (lost on the next
            # git reset --hard). A failed commit must not mask the primary
            # failure — wrap and log only.
            failed_artifacts = [p for p in (raw_json, stdout_log, crash_log) if p.exists()]
            if failed_artifacts:
                try:
                    self._commit_and_push(failed_artifacts, f"bench: {build} llm-inference-bench FAILED artifacts")
                except Exception as commit_err:  # noqa: BLE001
                    log.line(f"[bench] {build} FAILED-artifact commit skipped: {commit_err}")
            raise

    def _bench_command(self, port: int, overrides: dict, raw_json: Path) -> list:
        cmd = [
            "python3", str(self.config.bench_script),
            "--host", "localhost",
            "--port", str(port),
            "--concurrency", overrides.get("concurrency", self.config.default_concurrency),
            "--contexts", overrides.get("contexts", self.config.default_contexts),
            "--duration", str(overrides.get("duration", self.config.default_duration)),
            "--max-tokens", str(overrides.get("max_tokens", self.config.default_max_tokens)),
            "--kv-budget", str(overrides.get("kv_budget", self.config.default_kv_budget)),
            "--output", str(raw_json),
        ]
        prefill_contexts = overrides.get("prefill_contexts")
        if prefill_contexts:
            cmd += ["--prefill-contexts", str(prefill_contexts)]
        model = overrides.get("model")
        if model:
            cmd += ["--model", str(model)]
        engine = overrides.get("engine")
        if engine:
            cmd += ["--engine", str(engine)]
        return cmd

    def _build_overrides(self, build: str) -> dict:
        """Optional bench: overrides from builds/<build>/build.yaml. Missing
        file or section -> empty dict (defaults used)."""
        build_yaml = self.config.checkout_dir / "builds" / build / "build.yaml"
        if not build_yaml.exists():
            return {}
        try:
            data = yaml.safe_load(build_yaml.read_text()) or {}
        except (yaml.YAMLError, OSError) as e:
            log.line(f"[bench] WARNING: could not parse {build_yaml}: {e}; using defaults")
            return {}
        return dict(data.get("bench") or {})

    def _run_bench_timed(self, bench_cmd: list, stdout_log: Path, build: str, info: dict, timeout_s: int | None = None) -> bool:
        """Run the tool, capturing stdout. Returns True if the model
        container crashed during the run (caller restarts + re-runs)."""
        timeout_s = timeout_s if timeout_s is not None else self.config.build_timeout_s
        with open(stdout_log, "w") as logf:
            # Pipe stdout and tee it: the full transcript lands in the
            # committed stdout_log while each line also streams into the run
            # activity log, so the UI is never silent during a long bench.
            proc = subprocess.Popen(
                bench_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            reader = threading.Thread(target=self._tee_bench, args=(proc, logf), daemon=True)
            reader.start()
            started = time.time()
            last_heartbeat = started
            probe_failures = 0
            tick = self.config.crash_probe_interval_s
            try:
                while True:
                    try:
                        proc.wait(timeout=tick)
                        break
                    except subprocess.TimeoutExpired:
                        elapsed = time.time() - started
                        if elapsed > timeout_s:
                            proc.kill()
                            logf.flush()
                            raise RuntimeError(
                                f"Benchmark exceeded {timeout_s}s timeout for {build}"
                            )
                        # Crash detection is a quiet health probe, not a
                        # docker-ps poll: the container can stay "running"
                        # while the model server dies inside it.
                        port = info.get("port")
                        if not info["always_up"] and port is not None:
                            if self._probe(port):
                                probe_failures = 0
                            else:
                                probe_failures += 1
                                if probe_failures >= self.config.crash_probe_failures:
                                    proc.kill()
                                    logf.flush()
                                    return True
                        # Throttled heartbeat so a long, output-buffered bench
                        # still shows progress. Skip it if activity is recent.
                        if elapsed - last_heartbeat >= self.config.bench_heartbeat_s:
                            last_heartbeat = elapsed
                            last_activity = log.last_line_at() or started
                            if elapsed - last_activity >= self.config.bench_heartbeat_s / 2:
                                log.line(
                                    f"[bench] {build} still running — {int(elapsed)}s elapsed, health OK"
                                )
                if proc.returncode != 0:
                    # Nonzero exit with no container crash: the tool exited
                    # on its own (e.g. "No results collected" path exits 0,
                    # but a metrics-required SGLang path sys.exit(1)). Treat
                    # as failure; validation below adds the specific reason.
                    raise RuntimeError(f"llm_decode_bench.py exited {proc.returncode} for {build}")
            finally:
                reader.join(timeout=5)
                logf.flush()
        return False

    @staticmethod
    def _tee_bench(proc: subprocess.Popen, logf):
        for line in proc.stdout:
            logf.write(line)
            logf.flush()
            log.line(line.rstrip("\n"))
        logf.flush()

    def _save_crash_log(self, build: str, crash_log: Path):
        log = dc.run(["docker", "logs", build, "--tail", "300"], check=False).stdout
        crash_log.write_text(log)

    def _validate_results(self, raw_json: Path):
        if not raw_json.exists():
            raise RuntimeError(f"No results file written: {raw_json.relative_to(self.config.checkout_dir)}")
        try:
            data = json.loads(raw_json.read_text())
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Results file is not valid JSON: {raw_json.relative_to(self.config.checkout_dir)} ({e})")
        results = data.get("results") or []
        # Mirror benchmark_orchestrator.py's zero-completions hard-fail: a
        # benchmark that completed zero requests produced no usable data and
        # must never be committed as if it were real.
        completed = sum(1 for r in results if r.get("num_completed", 0) > 0)
        if not results or completed == 0:
            raise RuntimeError(
                f"No completions in {raw_json.relative_to(self.config.checkout_dir)} "
                f"({len(results)} cells, 0 completed) — refusing to trust empty data"
            )

    # ------------------------------------------------------------------
    # Git commit/push of results
    # ------------------------------------------------------------------

    def _commit_and_push(self, paths: list, message: str):
        checkout = self.config.checkout_dir
        env = self._git_env()
        rel = [str(Path(p).resolve().relative_to(checkout)) for p in paths]
        dc.run(["git", "pull", "--rebase", "origin", self.config.git_branch], cwd=str(checkout), env=env, timeout=300)
        dc.run(["git", "add", *rel], cwd=str(checkout), env=env)
        result = dc.run(["git", "commit", "-m", message], cwd=str(checkout), env=env, check=False)
        if result.returncode != 0:
            # Nothing staged (e.g. result identical to one already pushed) is
            # fine; anything else is a real error.
            if "nothing to commit" not in result.stdout:
                raise RuntimeError(f"git commit failed: {result.stdout[-2000:]}")
            return
        dc.run(["git", "push", "origin", self.config.git_branch], cwd=str(checkout), env=env, timeout=300)
