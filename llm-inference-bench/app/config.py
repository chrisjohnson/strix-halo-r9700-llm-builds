import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name, default):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass
class Config:
    checkout_dir: Path = Path(os.environ.get("BENCH_CHECKOUT", "/bench"))
    docker_dir: Path = Path(os.environ.get("BENCH_DOCKER_DIR", "/bench/docker"))
    repo_url: str = os.environ.get(
        "BENCH_REPO_URL", "git@github.com:chrisjohnson/strix-halo-r9700-llm-builds.git"
    )
    git_branch: str = os.environ.get("BENCH_GIT_BRANCH", "main")
    deploy_key: Path = Path(os.environ.get("BENCH_DEPLOY_KEY", "/bench-key/github_deploy_key"))
    known_hosts: Path = Path(os.environ.get("BENCH_KNOWN_HOSTS", "/bench-key/known_hosts"))
    git_author_name: str = os.environ.get("BENCH_GIT_AUTHOR_NAME", "strix-halo-r9700-llm-builds-bench")
    git_author_email: str = os.environ.get(
        "BENCH_GIT_AUTHOR_EMAIL", "strix-halo-r9700-llm-builds-bench@localhost"
    )
    ui_port: int = _env_int("BENCH_PORT", 8092)
    bench_script: Path = Path(os.environ.get("BENCH_SCRIPT", "/app/llm_decode_bench.py"))

    default_concurrency: str = os.environ.get("BENCH_DEFAULT_CONCURRENCY", "1,2,4,8")
    default_contexts: str = os.environ.get("BENCH_DEFAULT_CONTEXTS", "0,16384,32768,65536")
    default_duration: float = _env_float("BENCH_DEFAULT_DURATION", 30.0)
    default_max_tokens: int = _env_int("BENCH_DEFAULT_MAX_TOKENS", 8192)
    default_kv_budget: int = _env_int("BENCH_DEFAULT_KV_BUDGET", 0)

    build_timeout_s: int = _env_int("BENCH_BUILD_TIMEOUT_S", 7200)
    health_wait_s: int = _env_int("BENCH_HEALTH_WAIT_S", 1200)
    crash_probe_interval_s: float = _env_float("BENCH_CRASH_PROBE_INTERVAL_S", 10.0)
    crash_probe_failures: int = _env_int("BENCH_CRASH_PROBE_FAILURES", 3)
    bench_heartbeat_s: int = _env_int("BENCH_HEARTBEAT_S", 60)
    state_path: Path = field(init=False)

    def __post_init__(self):
        self.state_path = self.checkout_dir / "builds" / ".orchestrator" / "queue.json"
