"""Tee log helper for the orchestrator worker.

Every activity line (worker stage markers, echoed $ commands, subprocess
output) is written to BOTH the current run's activity log file — streamed
live to the UI — and the orchestrator's stdout (docker logs). The sink is
set/cleared by the worker thread around each run; outside a run it just
prints to stdout.
"""

from __future__ import annotations

import sys
import time

_sink = None
_last_line_at = None


def last_line_at():
    """Timestamp (time.time()) of the most recent line(), or None."""
    return _last_line_at


def set_sink(f):
    global _sink
    _sink = f


def clear_sink():
    global _sink
    _sink = None


def line(msg=""):
    global _last_line_at
    _last_line_at = time.time()
    text = msg.rstrip("\n")
    if _sink is not None:
        _sink.write(text + "\n")
        _sink.flush()
    print(text, flush=True)
