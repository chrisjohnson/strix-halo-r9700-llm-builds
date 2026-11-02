#!/usr/bin/env bash
# Fast-forward the orchestrator's dedicated bench checkout to origin/main so a
# freshly pushed build can be enqueued (POST /run validates build names against
# this checkout, which otherwise only syncs at the start of a run).
#
# Runs ON THE BOX as chris. Refuses to touch a checkout that is dirty or mid-run
# (a run is active when any llm_decode_bench process exists in the container).
set -euo pipefail
CK=/var/lib/git-checkouts/strix-halo-r9700-llm-builds
cd "$CK"
if [ -n "$(git status --porcelain)" ]; then
  echo "bench checkout is dirty; refusing" >&2; exit 1
fi
if curl -s http://127.0.0.1:8092/queue | python3 -c 'import sys,json; q=json.load(sys.stdin); runs=q if isinstance(q,list) else q.get("runs",[]); sys.exit(0 if any(r.get("status")=="running" for r in runs) else 1)'; then
  echo "a run is active; refusing" >&2; exit 1
fi
git fetch origin main
git merge --ff-only origin/main
git log --oneline -1
