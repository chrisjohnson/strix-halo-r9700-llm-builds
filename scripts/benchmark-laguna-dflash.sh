#!/usr/bin/env bash
# Real DFlash speculative-decoding benchmark for Laguna-S-2.1 on the poolside
# `laguna` fork. Run on the box, AFTER the matching build script.
#
# M-053: Vulkan build, the initial full run (3 short + 1 long prompt).
# M-055: parameterized sweep/control — override SPEC_N_MAX / FA_FLAG /
#        RESULT_DIR / MAX_TOKENS / N_SHORT env vars; defaults preserve the
#        M-053 invocation exactly.
# M-086: added DRAFT_MODEL_DIR / DRAFT_MODEL_FILE overrides so the same sweep
#        can run against quantized DFlash drafts (Q4_K_M / Q8_0), not just the
#        original BF16 draft. Defaults preserve the M-053/M-055 invocation
#        exactly.
#
# Follows catalog/OPERATIONS.md's safety procedure: pauses the download queue,
# stops exclusive (non-always-up) model services for GPU exclusivity, restores
# exactly what was running afterwards, and resumes the exact paused download units.
#
# Methodology matches the M-050 option-2 (Laguna-XS) run for apples-to-apples:
# real /v1/chat/completions request timings against a manual llama-server
# container, 3 short fresh prompts + 1 long-context prompt, capturing
# predicted_per_second + draft_n/draft_n_accepted. llama-bench has no spec-type
# support so live server timing is the only real measure.
set -uo pipefail

cd /var/lib/git-checkouts/strix-halo-r9700-llm-builds

IMAGE=${IMAGE:-strix-halo-r9700-llm-builds/llamacpp-laguna-fork:vulkan-radv}
PORT=${PORT:-8120}
SPEC_N_MAX=${SPEC_N_MAX:-15}
FA_FLAG=${FA_FLAG:--fa 1}
MAX_TOKENS=${MAX_TOKENS:-512}
N_SHORT=${N_SHORT:-3}
RESULT_DIR=${RESULT_DIR:-/tmp/laguna-dflash-results}
DRAFT_MODEL_DIR=${DRAFT_MODEL_DIR:-/var/lib/ai-models/laguna-s-2.1-dflash-draft}
DRAFT_MODEL_FILE=${DRAFT_MODEL_FILE:-laguna-s-2.1-DFlash-BF16.gguf}
mkdir -p "$RESULT_DIR"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

# ---- fingerprint capture (before we touch anything) ----
HOST_KERNEL=$(uname -r)
REPO_COMMIT=$(git rev-parse HEAD)
IMAGE_DIGEST=$(docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE" 2>/dev/null || echo "n/a")

# ---- pause activating download queue (OPERATIONS.md preflight) ----
PAUSED_UNITS=()
while read -r unit; do
  [ -n "$unit" ] && PAUSED_UNITS+=("$unit")
done < <(systemctl list-units "download-model-*" --all --no-legend | grep activating | awk '{print $2}')
if [ "${#PAUSED_UNITS[@]}" -gt 0 ]; then
  log "Pausing downloads: ${PAUSED_UNITS[*]}"
  sudo -n systemctl stop "${PAUSED_UNITS[@]}"
fi

# ---- stop exclusive (non-always-up) model services for GPU exclusivity ----
# Resolve via container ID (compose ps -q) -> docker inspect labels. The compose
# SERVICE name is not a valid `docker inspect` target (container names differ,
# e.g. litellm service = litellm-proxy container), so the first version of this
# misread infra services as exclusive and stopped litellm + turnstone — fixed.
STOPPED_SVCS=()
while read -r cid; do
  [ -n "$cid" ] || continue
  au=$(docker inspect --format '{{index .Config.Labels "com.local-ai-machine.always-up"}}' "$cid" 2>/dev/null || true)
  [ "$au" = "true" ] && continue
  svc=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$cid" 2>/dev/null || true)
  [ -n "$svc" ] && STOPPED_SVCS+=("$svc")
done < <(cd docker && docker compose ps -q 2>/dev/null)
if [ "${#STOPPED_SVCS[@]}" -gt 0 ]; then
  log "Stopping exclusive services: ${STOPPED_SVCS[*]}"
  (cd docker && docker compose stop "${STOPPED_SVCS[@]}")
fi

restore() {
  log "Teardown: removing test container BEFORE restoring services (restoring the 68GB standing laguna while the test container still holds its own 68GB load caused an OOM-kill of the test container, exit 137, on the first run)"
  docker rm -f laguna-dflash-test >/dev/null 2>&1 || true
  log "Teardown: restoring ${STOPPED_SVCS[*]:-none} + resuming ${PAUSED_UNITS[*]:-none}"
  if [ "${#STOPPED_SVCS[@]}" -gt 0 ]; then
    (cd docker && docker compose up -d "${STOPPED_SVCS[@]}")
    # OPERATIONS.md: confirm healthy BEFORE touching downloads
    for i in $(seq 1 120); do
      if curl -sf http://127.0.0.1:8101/health >/dev/null 2>&1; then
        log "Standing laguna service healthy"
        break
      fi
      sleep 5
    done
  fi
  if [ "${#PAUSED_UNITS[@]}" -gt 0 ]; then
    timeout 60 sudo -n systemctl start "${PAUSED_UNITS[@]}" || true
    log "Downloads resumed"
  fi
}
trap restore EXIT

# ---- start the DFlash server, falling back down the context ladder ----
started=""
for ctx in 131072 16384 8192; do
  log "Attempting load at -c $ctx"
  docker rm -f laguna-dflash-test >/dev/null 2>&1 || true
  docker run -d --name laguna-dflash-test \
    --device /dev/kfd --device /dev/dri --group-add 26 --group-add 303 \
    -v /var/lib/ai-models/laguna-s-2.1-118b-q4km:/models:ro \
    -v "$DRAFT_MODEL_DIR":/models-draft:ro \
    -p "127.0.0.1:$PORT:$PORT" \
    "$IMAGE" \
    /build/build/bin/llama-server \
    -m /models/UD-Q4_K_M/Laguna-S-2.1-UD-Q4_K_M-00001-of-00003.gguf \
    -md "/models-draft/$DRAFT_MODEL_FILE" \
    --spec-type draft-dflash --spec-draft-n-max "$SPEC_N_MAX" \
    -ngl 999 $FA_FLAG --swa-full --reasoning-format deepseek -n 8192 \
    -c "$ctx" --host 0.0.0.0 --port "$PORT" -a laguna-s-2.1-dflash \
    >/dev/null 2>&1 || { log "docker run failed at -c $ctx"; continue; }

  health_ok=0
  for i in $(seq 1 80); do
    if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then health_ok=1; break; fi
    if ! docker inspect -f '{{.State.Running}}' laguna-dflash-test 2>/dev/null | grep -q true; then break; fi
    sleep 5
  done
  if [ "$health_ok" = "1" ]; then started="$ctx"; break; fi
  log "Load failed at -c $ctx (container exited or health never came up). Last log lines:"
  docker logs laguna-dflash-test 2>&1 | tail -30
done

if [ -z "$started" ]; then
  log "DFLASH_LOAD_FAILED at all context sizes — clean no per M-053 plan. Full logs:"
  docker logs laguna-dflash-test 2>&1 | tail -100
  exit 1
fi
log "Server healthy at -c $started"

# ---- capture engine version from server log ----
docker logs laguna-dflash-test 2>&1 | grep -E "build:|version" | head -5 > "$RESULT_DIR/engine-version.txt" || true

# ---- run the benchmark ----
START_TS=$(date -u +%FT%TZ)
python3 - "$PORT" "$started" "$RESULT_DIR" "$START_TS" "$MAX_TOKENS" "$N_SHORT" "$SPEC_N_MAX" "$FA_FLAG" <<'PY'
import json, sys, time, urllib.request, uuid, datetime

port, ctx, outdir, start_ts = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
max_tokens = int(sys.argv[5]) if len(sys.argv) > 5 else 512
n_short = int(sys.argv[6]) if len(sys.argv) > 6 else 3
spec_n_max = sys.argv[7] if len(sys.argv) > 7 else "15"
fa_flag = sys.argv[8] if len(sys.argv) > 8 else "-fa 1"
base = f"http://127.0.0.1:{port}/v1/chat/completions"

def ask(prompt, max_tokens=max_tokens):
    payload = json.dumps({
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }).encode()
    req = urllib.request.Request(base, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())

def summarize(resp):
    t = resp.get("timings", {})
    return {
        "predicted_per_second": t.get("predicted_per_second"),
        "prompt_n": t.get("prompt_n"),
        "predicted_n": t.get("predicted_n"),
        "draft_n": t.get("draft_n"),
        "draft_n_accepted": t.get("draft_n_accepted"),
        "predicted_ms": t.get("predicted_ms"),
        "prompt_ms": t.get("prompt_ms"),
    }

topics = [
    "Explain the difference between SIMD and MIMD processor architectures, with concrete examples of each.",
    "Describe how speculative decoding works in large language model inference, including draft and verify steps.",
    "What are the practical tradeoffs between quantization schemes like Q4_K_M and BF16 for serving LLMs on unified memory?",
]
short_samples = []
for i, topic in enumerate(topics[:n_short]):
    prompt = f"{uuid.uuid4()} {topic}"
    resp = ask(prompt)
    with open(f"{outdir}/short-{i}.json", "w") as f:
        json.dump(resp, f)
    short_samples.append(summarize(resp))
    time.sleep(2)

paragraph = (
    "The economics of running large language models locally depend almost entirely on memory "
    "bandwidth and capacity. Unified-memory architectures collapse the traditional CPU/GPU "
    "memory boundary, trading raw off-chip bandwidth for the ability to hold larger models "
    "and longer contexts in a single coherent address space. For inference, the dominant cost "
    "is streaming model weights across the memory bus on every generated token, so token "
    "generation throughput tends to scale with effective bandwidth rather than raw FLOPs. "
    "Speculative decoding complicates this picture by spending extra compute on a smaller "
    "draft model whose predictions are then verified in parallel by the larger target model, "
    "converting idle memory bandwidth into increased acceptance of drafted tokens. "
)
long_text = paragraph * 90
long_prompt = f"{uuid.uuid4()} Write a technical summary of the following text: {long_text}"
resp = ask(long_prompt, max_tokens=256)
with open(f"{outdir}/long.json", "w") as f:
    json.dump(resp, f)
long_summary = summarize(resp)

print(json.dumps({
    "benchmark_id": "llamacpp-server-live-timing-v1",
    "started_utc": start_ts,
    "config": {"spec_n_max": spec_n_max, "fa_flag": fa_flag, "max_tokens": max_tokens},
    "context_used_tokens": int(ctx),
    "short_context_samples": short_samples,
    "long_context_sample": long_summary,
}, indent=2))
PY

END_TS=$(date -u +%FT%TZ)
log "Benchmark window: $START_TS .. $END_TS"
log "Fingerprint: host_kernel=$HOST_KERNEL repo_commit=$REPO_COMMIT image_digest=$IMAGE_DIGEST"
log "Config: SPEC_N_MAX=$SPEC_N_MAX FA_FLAG=$FA_FLAG MAX_TOKENS=$MAX_TOKENS N_SHORT=$N_SHORT"
log "Results + raw responses in $RESULT_DIR (engine-version.txt)"
log "DFLASH_BENCH_DONE"
