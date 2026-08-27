"""FastAPI web server for the benchmark orchestrator (LAN, no auth — keep
this off the WAN boundary, same convention as every other LAN-only service
in this stack). Startup also spawns the queue worker thread, so the queue
resumes across container restarts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .config import Config
from .orchestrator import Orchestrator

STATIC_DIR = Path(__file__).resolve().parent / "static"

config = Config()
orchestrator = Orchestrator(config)

app = FastAPI(title="llm-inference-bench orchestrator", version="1.0.0")


class RunRequest(BaseModel):
    runs: list[list[str]]


class RunCreate(BaseModel):
    # Single-run convenience: POST /run {"builds": [...]}
    builds: list[str]


class RunClose(BaseModel):
    status: str = "failed"  # "done" or "failed"
    error: Optional[str] = None


@app.on_event("startup")
def _startup():
    # Worker must be alive before the first request can enqueue something
    # the worker should pick up immediately.
    orchestrator.start()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/runs")
def enqueue_runs(req: RunRequest):
    if not req.runs:
        raise HTTPException(status_code=400, detail="runs must be a non-empty list")
    created = []
    for builds in req.runs:
        try:
            created.append(orchestrator.enqueue(builds))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    return {"created": created}


@app.post("/run")
def enqueue_run(req: RunCreate):
    if not req.builds:
        raise HTTPException(status_code=400, detail="builds must be a non-empty list")
    try:
        return {"created": orchestrator.enqueue(req.builds)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/queue")
def queue():
    return {"runs": orchestrator.list_runs()}


@app.get("/runs/{run_id}")
def get_run(run_id: str):
    run = orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return run


@app.post("/runs/{run_id}/close")
def close_run(run_id: str, req: RunClose):
    """Force a stuck run to a terminal state. Intended for the watchdog to
    close stale-running orphans the worker abandoned mid-flight; also usable
    manually to fail a run that can never complete. Idempotent for runs
    already terminal."""
    if req.status not in ("done", "failed"):
        raise HTTPException(status_code=400, detail="status must be 'done' or 'failed'")
    try:
        run = orchestrator.close_run(run_id, status=req.status, error=req.error)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    return run


async def _log_stream(path: Path, run_id: str):
    """SSE tail of a run's activity log. Replays existing content, then
    streams new lines as the worker appends them; closes with an `end` event
    once the run is terminal and the file is fully drained."""
    while not path.exists():
        # Queued runs have no activity file yet (worker hasn't picked them
        # up) — hold the stream open until it appears or the run goes
        # terminal without ever creating one.
        if orchestrator.run_terminal(run_id):
            yield "event: end\ndata: {}\n\n"
            return
        yield ": waiting\n\n"
        await asyncio.sleep(1)
    with open(path) as f:
        while True:
            line = f.readline()
            if line:
                yield f"data: {line.rstrip()}\n\n"
                continue
            if orchestrator.run_terminal(run_id):
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(1)


@app.get("/runs/{run_id}/log")
async def run_log(run_id: str, build: Optional[str] = None, stream: bool = False):
    run = orchestrator.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    if build is not None:
        if build not in run.get("per_build", {}):
            raise HTTPException(status_code=404, detail=f"no build {build} in run {run_id}")
        rel = run["per_build"][build].get("stdout_log")
        if not rel:
            return PlainTextResponse("")
        path = config.checkout_dir / rel
    else:
        path = orchestrator.activity_log_path(run_id)
    if stream:
        return StreamingResponse(
            _log_stream(path, run_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if not path.exists():
        return PlainTextResponse("")
    return PlainTextResponse(path.read_text())


@app.get("/builds")
def builds():
    services = orchestrator.services()
    valid = [
        {
            "name": name,
            "always_up": info["always_up"],
            "port": info["port"],
            "has_build_yaml": (config.checkout_dir / "builds" / name / "build.yaml").exists(),
            "benchmarkable": (not info["always_up"]) or orchestrator._always_up_benchmarkable(name),
        }
        for name, info in sorted(services.items())
        if (not info["always_up"]) or orchestrator._always_up_benchmarkable(name)
    ]
    return {"builds": valid}


@app.get("/state")
def state_file():
    path = config.state_path
    if not path.exists():
        return {"state": None}
    return FileResponse(path)
