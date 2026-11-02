#!/usr/bin/env bash
# Fast-forward the orchestrator's dedicated bench checkout to origin/main so a
# freshly pushed build can be enqueued (POST /run validates build names against
# this checkout, which otherwise only syncs at the start of a run).
#
# Runs ON THE BOX as chris. Refuses to touch a checkout that is dirty or mid-run
# (see the active-run check below).
set -euo pipefail
CK=/var/lib/git-checkouts/strix-halo-r9700-llm-builds
cd "$CK"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "bench checkout has tracked modifications; refusing" >&2; exit 1
fi
# A run is active if one is marked running and started within the last 6 h
# (older "running" entries are stale queue state, not live work).
if curl -s http://127.0.0.1:8092/queue | python3 -c '
import sys, json, datetime as d
q = json.load(sys.stdin); now = d.datetime.now(d.timezone.utc)
live = [r for r in q if r.get("status") == "running" and r.get("started_at")
        and (now - d.datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))).total_seconds() < 6 * 3600]
sys.exit(0 if live else 1)'; then
  echo "a run is active; refusing" >&2; exit 1
fi
git fetch origin main
git merge --ff-only origin/main
git log --oneline -1
