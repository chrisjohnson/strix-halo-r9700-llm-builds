#!/usr/bin/env python3
"""
LLM Inference Benchmark with Rich TUI Dashboard.

Measures decode throughput across a matrix of concurrency levels and context lengths.
Auto-detects SGLang or vLLM engine and adapts metrics accordingly.

Usage:
    python3 llm_decode_bench.py
    python3 llm_decode_bench.py --port 5199 --concurrency 1,2,4 --contexts 0,16384
    python3 llm_decode_bench.py --port 5199 --kv-budget 692736
    python3 llm_decode_bench.py --port 5001 --max-tokens 4096
"""

import argparse
import asyncio
import json
import os
import random
import re
import string
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from statistics import mean, median
from typing import Optional

import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 4

# Cap on the prefill "warmup 2" context. That step exists only to trigger
# prefill graph/JIT compilation before measurement - it uses a different body
# from the measured text, so it cannot warm the measured text's pages. At a
# large --prefill-contexts value an uncapped warmup becomes a second full-size
# prefill: at a 256k context it cost 1768s on its own (measured 2026-09-27),
# roughly doubling the prefill phase. Graphs are built per ubatch shape, so a
# few thousand tokens is enough.
WARMUP_MAX_CTX = 8192

# Padding text used to synthesise long-context prompts.
#
# This was a fixed list of 20 sentences cycled with
# `PADDING_SENTENCES[idx % len(PADDING_SENTENCES)]`. That produced a context
# whose *entire* trigram set is a few hundred entries, so a model carrying an
# n-gram/PLE table (qwen3.8-flash-next: a ~26.8 GiB PLE table keyed on
# 3-grams) only ever touched a working set small enough to stay
# cache-resident. Prefill measured on such text under-reports the real
# cold-read cost - exactly the trap called out on llama.cpp PR #29030 ("any
# benchmark built from repeated filler will show this PR doing nothing"), and
# the reason this generator was replaced 2026-09-27.
#
# Sentence count here is combinatorial rather than fixed - templates x slot
# vocabularies - so distinct trigrams scale with context length the way real
# prose does and the PLE table is genuinely exercised. Everything is drawn
# from a seeded RNG, so a given (padding seed, context) always reproduces
# byte-identical text and two builds can be A/B'd against identical input.
PADDING_TEMPLATES = [
    "{subject} {verb} {object}{clause}.",
    "In {era}, {subject} {verb} {object}{clause}.",
    "{adverb}, {subject} {verb} {object}{clause}.",
    "{subject} {verb} {object}, while {subject2} {verb2} {object2}{clause}.",
    "Although {subject} {verb} {object}, {subject2} {verb2} {object2}{clause}.",
    "The {adj} {noun} {verb} {object}{clause}.",
    "{subject} {verb} that {subject2} {verb2} {object2}{clause}.",
    "Whenever {subject} {verb} {object}, the {adj} {noun} {verb2} {object2}{clause}.",
]

PADDING_SUBJECTS = [
    "the scheduler", "the compiler", "the runtime", "the memory controller",
    "the prefetch engine", "the attention kernel", "the router network",
    "the quantization pass", "the tokenizer", "the embedding table",
    "the page cache", "the scratch allocator", "the tensor loader",
    "the collective backend", "the inference server", "the batch scheduler",
    "the kernel dispatcher", "the graph rewriter", "the cache invalidation pass",
    "the speculative decoder", "the expert dispatcher", "the gradient checkpoint",
    "the fusion pass", "the sharding planner", "the KV manager",
    "the admission controller", "the profiler", "the trace collector",
    "the weight streaming layer", "the numerics library", "the sampler",
    "the pipeline stage", "the reduction tree", "the device queue",
    "the command processor", "the bandwidth estimator", "the layout planner",
    "the calibration routine", "the fallback path", "the verification harness",
]

PADDING_VERBS = [
    "reorders", "coalesces", "throttles", "relaxes", "rebalances", "serializes",
    "overlaps", "batches", "partitions", "annotates", "fuses", "tiles",
    "streams", "checkpoints", "evicts", "promotes", "demotes", "speculates",
    "amortizes", "pins", "prefetches", "compresses", "quantizes", "aligns",
    "pipelines", "duplicates", "migrates", "drains", "backpressures", "unrolls",
    "specializes", "inlines", "schedules", "estimates", "reconciles",
    "arbitrates", "caches", "invalidates", "replays", "truncates",
]

PADDING_OBJECTS = [
    "the incoming request stream", "tensor fragments across the fabric",
    "the resident weight set", "every outstanding memory transaction",
    "the hot path through the kernel", "the per-layer activation buffer",
    "the sparse expert selection", "the long-context key blocks",
    "the staging buffer pool", "the instruction window",
    "the shared embedding rows", "the intermediate reductions",
    "the device-side queue", "the host-side ring buffer",
    "the scratchpad allocation", "the compressed weight pages",
    "the attention mask layout", "the position encoding tables",
    "the router logits", "the output projection", "the residual stream",
    "the paged KV blocks", "the descriptor ring", "the completion queue",
    "the prefetch distances", "the occupancy heuristic", "the tile shapes",
    "the boundary conditions", "the alignment requirements",
    "the eviction order", "the reuse distance", "the working set estimate",
    "the bandwidth budget", "the latency target", "the throughput ceiling",
    "the thermal envelope", "the power state transition",
    "the clock domain crossing", "the memory fence",
    "the synchronization barrier",
]

PADDING_CLAUSES = [
    "", "", "", "",
    " without stalling the pipeline",
    " before the next barrier",
    " under sustained load",
    " at the cost of extra bandwidth",
    " as the working set grows",
    " once the queue saturates",
    " while the device stays busy",
    " in the steady state",
    " for reasons that remain unclear",
    " with predictable latency",
    " despite the added complexity",
    " whenever the cache misses",
    " across every active slot",
    " long before the deadline",
    " at roughly constant cost",
    " and the measurement confirms it",
]

PADDING_ERAS = [
    "the early days of the project", "the first optimization pass",
    "the initial bring-up", "the migration to a new backend",
    "the transition to paged memory", "the second generation of hardware",
    "the pre-quantization era", "the era of hand-written kernels",
    "the consolidation phase", "the period before batching",
    "the initial benchmark sweep", "the long debugging session",
    "the port to a new instruction set", "the rewrite of the loader",
    "the introduction of speculative decoding",
    "the switch to unified memory", "the era of static graphs",
    "the first production deployment", "the capacity planning exercise",
    "the second round of profiling",
]

PADDING_ADVERBS = [
    "Curiously", "In practice", "By design", "On closer inspection",
    "Empirically", "For the most part", "Under contention", "Predictably",
    "Counterintuitively", "With enough headroom", "At steady state",
    "Given the constraints", "In the common case", "As a rule",
    "Despite the overhead", "After warmup", "Without warning",
    "More often than not", "In the worst case",
    "Subject to measurement error",
]

PADDING_ADJS = [
    "resident", "sparse", "dense", "paged", "unified", "pinned", "streamed",
    "compressed", "fused", "tiled", "sharded", "replicated", "speculative",
    "adaptive", "static", "dynamic", "asynchronous", "coalesced", "vectorized",
    "quantized", "hierarchical", "distributed", "synchronous",
    "opportunistic", "conservative", "aggressive", "idempotent", "monotonic",
    "amortized", "latency-bound",
]

PADDING_NOUNS = [
    "scheduler", "allocator", "dispatcher", "decoder", "collective",
    "prefetcher", "estimator", "profiler", "checkpoint", "reduction",
    "barrier", "fence", "queue", "ring", "tile", "kernel", "shard",
    "replica", "pipeline", "cache", "buffer", "descriptor", "window",
    "heuristic", "threshold", "budget", "envelope", "estimate", "planner",
    "harness",
]

GENERATION_PROMPT = (
    "Write an extremely detailed, comprehensive encyclopedia article about the complete "
    "history of mathematics from ancient Mesopotamia to 2025. Cover every civilization, "
    "every major mathematician, every theorem, proof, and breakthrough. Include detailed "
    "biographical information, historical context, and mathematical explanations. "
    "Do not summarize - provide maximum detail on every topic."
)

METRIC_RE = re.compile(r'^((?:sglang|vllm):\w+)(?:\{([^}]*)\})?\s+([\d.eE+-]+)')

# Engine types
ENGINE_SGLANG = "sglang"
ENGINE_VLLM = "vllm"
ENGINE_OLLAMA = "ollama"
ENGINE_AUTO = "auto"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StreamResult:
    ttft: float = 0.0
    total_tokens: int = 0
    total_time: float = 0.0
    tokens_per_sec: float = 0.0
    error: Optional[str] = None


@dataclass
class CellResult:
    concurrency: int = 0
    context_tokens: int = 0
    aggregate_tps: float = 0.0
    per_request_avg_tps: float = 0.0
    ttft_avg: float = 0.0
    ttft_p50: float = 0.0
    ttft_p99: float = 0.0
    total_tokens: int = 0
    wall_time: float = 0.0
    num_completed: int = 0
    num_errors: int = 0
    server_gen_throughput: float = 0.0
    server_utilization: float = 0.0
    server_spec_accept_rate: float = 0.0
    # Queue / effective concurrency tracking
    avg_running_reqs: float = 0.0
    max_running_reqs: int = 0
    avg_queue_reqs: float = 0.0
    max_queue_reqs: int = 0
    queue_fraction: float = 0.0  # fraction of samples where queue > 0


@dataclass
class TUIState:
    # Overall
    engine: str = ENGINE_SGLANG
    model_name: str = ""
    server_url: str = ""
    total_tests: int = 0
    completed_tests: int = 0
    overall_start: float = 0.0
    # Current cell
    current_concurrency: int = 0
    current_context: int = 0
    cell_start: float = 0.0
    cell_duration: float = 20.0
    cell_tokens: int = 0
    cell_live_tps: float = 0.0
    cell_running: bool = False
    cell_warmup: bool = False  # True during prefill ramp-up before measurement
    cell_measurement_start: float = 0.0  # when actual measurement begins (after warmup)
    # Server metrics
    srv_gen_throughput: float = 0.0
    srv_running_reqs: int = 0
    srv_queue_reqs: int = 0
    srv_utilization: float = 0.0
    srv_spec_accept_rate: float = 0.0
    srv_spec_accept_length: float = 0.0
    # Results
    results: dict = field(default_factory=dict)  # (ctx, conc) -> aggregate_tps
    errors: dict = field(default_factory=dict)   # (ctx, conc) -> num_errors
    queue_info: dict = field(default_factory=dict)  # (ctx, conc) -> (avg_running, avg_queue)
    concurrency_levels: list = field(default_factory=list)
    context_lengths: list = field(default_factory=list)
    # Prefill results: ctx -> {ttft, tok_per_sec}
    prefill_results: dict = field(default_factory=dict)
    prefill_contexts: list = field(default_factory=list)
    prefill_phase: bool = False
    # Server limits
    kv_cache_budget: int = 0
    max_running_requests: int = 0
    skipped_cells: int = 0
    max_tokens: int = 0
    # Timing
    cell_times: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compose_sentence(rng: random.Random) -> str:
    """One synthetic sentence from a random template + random slot fills."""
    return rng.choice(PADDING_TEMPLATES).format(
        subject=rng.choice(PADDING_SUBJECTS),
        subject2=rng.choice(PADDING_SUBJECTS),
        verb=rng.choice(PADDING_VERBS),
        verb2=rng.choice(PADDING_VERBS),
        object=rng.choice(PADDING_OBJECTS),
        object2=rng.choice(PADDING_OBJECTS),
        clause=rng.choice(PADDING_CLAUSES),
        era=rng.choice(PADDING_ERAS),
        adverb=rng.choice(PADDING_ADVERBS),
        adj=rng.choice(PADDING_ADJS),
        noun=rng.choice(PADDING_NOUNS),
    )


def generate_padding_text(target_tokens: int, seed=0) -> str:
    """Synthesise ~target_tokens of high-trigram-diversity prose.

    Deterministic for a given (seed, target_tokens) - the whole point of the
    seed is that two benchmark runs, or two builds being A/B'd, receive
    byte-identical input. Callers wanting genuinely different text for
    different context lengths pass a per-context seed (see the context_cache
    build in main()).
    """
    target_chars = target_tokens * CHARS_PER_TOKEN
    rng = random.Random(seed)
    sentences = []
    current_chars = 0
    previous = None
    while current_chars < target_chars:
        sentence = _compose_sentence(rng)
        if sentence == previous:
            # Immediate repeats are the one pattern worth suppressing
            # outright: they would hand the model a duplicated trigram it
            # just looked up.
            continue
        previous = sentence
        sentences.append(sentence)
        current_chars += len(sentence) + 1
    return " ".join(sentences)


def _corpus_slice(corpus: str, target_chars: int, seed) -> str:
    """A deterministic window of `target_chars` taken from a real corpus.

    Each context takes its own seeded offset rather than a shared prefix, so
    a longer context is not a superset of a shorter one - measuring the
    longer context second would otherwise read text whose pages an earlier
    measurement had already faulted in, which is the exact cost under test.
    A corpus shorter than the requested context has to be tiled; that
    reintroduces repetition, so main() warns when it happens.
    """
    if len(corpus) >= target_chars:
        rng = random.Random(seed)
        start = rng.randrange(0, len(corpus) - target_chars + 1)
        return corpus[start:start + target_chars]
    reps = (target_chars // max(len(corpus), 1)) + 1
    return (corpus * reps)[:target_chars]


def trigram_stats(text: str) -> dict:
    """Distinct vs total word trigrams in `text`.

    Recorded with every prefill result so a result file documents its own
    coverage instead of leaving it to be inferred from whatever generated the
    text. It matters because qwen3.8-flash-next's ~26.8 GiB PLE table is keyed
    on 3-grams: a periodic prompt pins the distinct count (the old 20-sentence
    generator sat at 327 at every length) while a real corpus grows it with
    length. Two numbers that look comparable can therefore exercise that table
    by 100x different amounts - see knowledge/research/
    2026-09-27-prefill-bench-padding-trap.md.
    """
    words = text.split()
    total = max(len(words) - 2, 0)
    if total == 0:
        return {"trigram_total": 0, "trigram_distinct": 0, "trigram_distinct_ratio": 0.0}
    distinct = len({(words[i], words[i + 1], words[i + 2]) for i in range(total)})
    return {
        "trigram_total": total,
        "trigram_distinct": distinct,
        "trigram_distinct_ratio": round(distinct / total, 4),
    }


def build_messages(context_tokens: int, context_text: str) -> list:
    messages = []
    if context_tokens > 0 and context_text:
        messages.append({
            "role": "user",
            "content": (
                "Below is a large reference document. Read it carefully, "
                "then answer the question that follows.\n\n"
                "--- BEGIN REFERENCE DOCUMENT ---\n"
                f"{context_text}\n"
                "--- END REFERENCE DOCUMENT ---"
            )
        })
        messages.append({
            "role": "assistant",
            "content": "I have read the entire reference document. Please ask your question."
        })
    messages.append({"role": "user", "content": GENERATION_PROMPT})
    return messages


def percentile(data: list, p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def format_context(ctx: int) -> str:
    if ctx == 0:
        return "0"
    elif ctx >= 1024:
        return f"{ctx // 1024}k"
    return str(ctx)


def format_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


# ---------------------------------------------------------------------------
# Metrics scraping
# ---------------------------------------------------------------------------

async def scrape_metrics(client: httpx.AsyncClient, base_url: str) -> dict:
    metrics = {}
    try:
        resp = await client.get(f"{base_url}/metrics", timeout=5.0)
        for line in resp.text.splitlines():
            if line.startswith("#"):
                continue
            m = METRIC_RE.match(line)
            if m:
                name, labels, value = m.group(1), m.group(2) or "", float(m.group(3))
                # Only take tp_rank=0 metrics to avoid duplicates
                if "tp_rank=" in labels and 'tp_rank="0"' not in labels:
                    continue
                key = f"{name}|{labels}" if labels else name
                metrics[key] = value
    except Exception:
        pass
    return metrics


def extract_metric(metrics: dict, name: str, label_filter: str = "") -> float:
    for key, val in metrics.items():
        if key.startswith(name):
            if label_filter and label_filter not in key:
                continue
            return val
    return 0.0


def extract_label(metrics: dict, metric_name: str, label: str) -> str:
    """Extract a label value from a labeled Prometheus metric."""
    for key in metrics:
        if key.startswith(metric_name):
            m = re.search(rf'{label}="([^"]*)"', key)
            if m:
                return m.group(1)
    return ""


def metric_name(engine: str, key: str) -> str:
    """Map a logical metric key to engine-specific Prometheus metric name."""
    names = {
        ENGINE_SGLANG: {
            "gen_throughput": "sglang:gen_throughput",
            "running_reqs": "sglang:num_running_reqs",
            "queue_reqs": "sglang:num_queue_reqs",
            "utilization": "sglang:utilization",
            "spec_accept_rate": "sglang:spec_accept_rate",
            "spec_accept_length": "sglang:spec_accept_length",
            "gen_tokens_total": "sglang:generation_tokens_total",
        },
        ENGINE_VLLM: {
            "gen_throughput": "vllm:avg_generation_throughput_toks_per_s",
            "running_reqs": "vllm:num_requests_running",
            "queue_reqs": "vllm:num_requests_waiting",
            "utilization": "vllm:kv_cache_usage_perc",
            "spec_accept_rate": "",
            "spec_accept_length": "",
            "gen_tokens_total": "vllm:generation_tokens_total",
        },
        # Ollama exposes no Prometheus /metrics (its OpenAI-compat layer does
        # not serve one), so every server-side metric maps to "". extract_metric
        # returns 0.0 for an unknown name; the client-side tokens/sec from the
        # SSE chunks remains the real throughput signal.
        ENGINE_OLLAMA: {
            "gen_throughput": "",
            "running_reqs": "",
            "queue_reqs": "",
            "utilization": "",
            "spec_accept_rate": "",
            "spec_accept_length": "",
            "gen_tokens_total": "",
        },
    }
    return names.get(engine, names[ENGINE_SGLANG]).get(key, "")


# ---------------------------------------------------------------------------
# Streaming request
# ---------------------------------------------------------------------------

async def stream_one_request(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    index: int,
    cancel_event: asyncio.Event,
    shared_token_count: list,
    shared_active_streams: list = None,
) -> StreamResult:
    result = StreamResult()
    t_start = time.monotonic()
    t_first = None
    char_count = 0
    chunk_count = 0
    usage_tokens = None

    try:
        async with client.stream("POST", url, json=payload, timeout=httpx.Timeout(600.0, connect=30.0)) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                result.error = f"HTTP {resp.status_code}: {body.decode()[:200]}"
                result.total_time = time.monotonic() - t_start
                return result

            async for line in resp.aiter_lines():
                if cancel_event.is_set():
                    break

                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Check for usage in final chunk (stream_options.include_usage)
                usage = data.get("usage")
                if usage and "completion_tokens" in usage:
                    usage_tokens = usage["completion_tokens"]

                if "choices" not in data or len(data["choices"]) == 0:
                    continue

                delta = data["choices"][0].get("delta", {})
                text = ""

                reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                if reasoning:
                    text += reasoning

                content = delta.get("content")
                if content:
                    text += content

                if text:
                    if t_first is None:
                        t_first = time.monotonic()
                        if shared_active_streams is not None:
                            shared_active_streams[0] += 1
                    char_count += len(text)
                    chunk_count += 1
                    # Each SSE chunk = 1 token (verified on vLLM and SGLang)
                    shared_token_count[0] += 1

    except httpx.ReadTimeout:
        result.error = "ReadTimeout"
    except httpx.ConnectError as e:
        result.error = f"ConnectError: {e}"
    except httpx.RemoteProtocolError as e:
        result.error = f"ProtocolError: {e}"
    except asyncio.CancelledError:
        pass
    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"

    t_end = time.monotonic()
    # Use server-reported usage if available, else estimate from chars
    if usage_tokens is not None:
        result.total_tokens = usage_tokens
    else:
        # Fallback: 1 SSE chunk = 1 token
        result.total_tokens = chunk_count
    result.total_time = t_end - t_start
    if t_first is not None:
        result.ttft = t_first - t_start
    if result.total_tokens > 0 and result.total_time > 0:
        result.tokens_per_sec = result.total_tokens / result.total_time

    return result


# ---------------------------------------------------------------------------
# Run one cell
# ---------------------------------------------------------------------------

async def run_one_cell(
    client: httpx.AsyncClient,
    base_url: str,
    concurrency: int,
    context_tokens: int,
    context_text: str,
    duration: float,
    max_tokens: int,
    model: str,
    state: TUIState,
    live: Live,
    engine: str = ENGINE_SGLANG,
) -> CellResult:
    messages = build_messages(context_tokens, context_text)
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
        "stream_options": {"include_usage": True},
    }

    url = f"{base_url}/v1/chat/completions"
    cancel_event = asyncio.Event()
    shared_token_count = [0]
    shared_active_streams = [0]  # how many streams have received first token

    # Fresh client per cell — avoids stale keepalive connections from previous cells
    cell_limits = httpx.Limits(
        max_connections=concurrency + 10,
        max_keepalive_connections=concurrency + 5,
    )
    cell_client = httpx.AsyncClient(limits=cell_limits)

    # Update TUI state
    state.current_concurrency = concurrency
    state.current_context = context_tokens
    state.cell_start = time.monotonic()
    state.cell_duration = duration
    state.cell_tokens = 0
    state.cell_live_tps = 0.0
    state.cell_running = True
    state.cell_warmup = True

    # Scout request: ensure prefix cache is warm before launching full concurrency.
    # Send one request with max_tokens=1 to populate/refresh prefix cache,
    # then all C requests will get cache hits instead of competing for prefill.
    if context_tokens > 0:
        scout_payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": 1,
        }
        try:
            async with client.stream("POST", url, json=scout_payload,
                                     timeout=httpx.Timeout(600.0, connect=30.0)) as resp:
                async for line in resp.aiter_lines():
                    if line and line.startswith("data: [DONE]"):
                        break
        except Exception:
            pass
        live.update(build_display(state))

    # Launch all streams on fresh client (no stale keepalive connections)
    tasks = [
        asyncio.create_task(
            stream_one_request(cell_client, url, payload, i, cancel_event,
                               shared_token_count, shared_active_streams)
        )
        for i in range(concurrency)
    ]

    # Monitor loop — collect server gen_throughput samples for accurate measurement
    metrics_interval = 1.0
    min_warmup_seconds = 2.0   # minimum warmup (CUDA graph etc.)
    max_warmup_seconds = 60.0  # give up waiting for queue to drain
    last_metrics_time = 0.0
    gen_throughput_samples = []
    # For vLLM: compute throughput rate from generation_tokens counter
    prev_gen_tokens = None
    prev_gen_time = None
    # Queue tracking: collect running/queue samples after warmup
    running_reqs_samples = []
    queue_reqs_samples = []
    # Dynamic warmup: wait until all requests are in decode (queue == 0)
    warmup_done = False
    warmup_stable_since = None  # time when queue first hit 0 after min_warmup
    measurement_start = None    # reset timer after warmup for full duration measurement
    measurement_tokens_start = 0  # token count at measurement start (for client-side fallback)

    while True:
        await asyncio.sleep(0.5)
        now = time.monotonic()
        elapsed = now - state.cell_start

        # Update token counts from client-side estimate (for TUI only)
        state.cell_tokens = shared_token_count[0]
        state._active_streams = shared_active_streams[0]

        # Scrape server metrics periodically
        if now - last_metrics_time > metrics_interval:
            metrics = await scrape_metrics(client, base_url)

            # Throughput: SGLang has a gauge, vLLM needs rate from counter
            if engine == ENGINE_SGLANG:
                state.srv_gen_throughput = extract_metric(metrics, metric_name(engine, "gen_throughput"))
            else:
                # Try vLLM v0 gauge first
                tp = extract_metric(metrics, metric_name(engine, "gen_throughput"))
                if tp > 0:
                    state.srv_gen_throughput = tp
                else:
                    # vLLM v1: compute rate from generation_tokens counter
                    gen_total = extract_metric(metrics, metric_name(engine, "gen_tokens_total"))
                    if gen_total > 0 and prev_gen_tokens is not None:
                        dt = now - prev_gen_time
                        if dt > 0.1:
                            state.srv_gen_throughput = (gen_total - prev_gen_tokens) / dt
                    prev_gen_tokens = gen_total
                    prev_gen_time = now

            state.srv_running_reqs = int(extract_metric(metrics, metric_name(engine, "running_reqs")))
            state.srv_queue_reqs = int(extract_metric(metrics, metric_name(engine, "queue_reqs")))
            state.srv_utilization = extract_metric(metrics, metric_name(engine, "utilization"))
            state.srv_spec_accept_rate = extract_metric(metrics, metric_name(engine, "spec_accept_rate"))
            state.srv_spec_accept_length = extract_metric(metrics, metric_name(engine, "spec_accept_length"))

            # Dynamic warmup: wait for min_warmup AND queue==0 AND tokens flowing
            # All three conditions ensure:
            #   - CUDA graphs / JIT compiled (min_warmup)
            #   - all requests past prefill (queue==0)
            #   - tokens actually being generated (server OR client-side detection)
            if not warmup_done:
                if elapsed >= min_warmup_seconds:
                    # All streams must have received their first token before measurement.
                    # This prevents measuring before slow-to-prefill requests start decoding.
                    all_streams_active = shared_active_streams[0] >= concurrency
                    generating = state.srv_gen_throughput > 0 or shared_token_count[0] > 0
                    server_ready = state.srv_queue_reqs == 0 and generating and all_streams_active
                    if server_ready:
                        if warmup_stable_since is None:
                            warmup_stable_since = now
                        # Require 1s of stable conditions to avoid transient dips
                        elif now - warmup_stable_since >= 1.0:
                            warmup_done = True
                            state.cell_warmup = False
                            measurement_start = now
                            state.cell_measurement_start = now
                            measurement_tokens_start = shared_token_count[0]
                    else:
                        warmup_stable_since = None
                    # Give up after max_warmup — queue never drained (real capacity issue)
                    if elapsed >= max_warmup_seconds:
                        warmup_done = True
                        state.cell_warmup = False
                        measurement_start = now
                        state.cell_measurement_start = now
                        measurement_tokens_start = shared_token_count[0]

            # Collect samples only after warmup is done
            if warmup_done:
                if state.srv_gen_throughput > 0:
                    gen_throughput_samples.append(state.srv_gen_throughput)
                running_reqs_samples.append(state.srv_running_reqs)
                queue_reqs_samples.append(state.srv_queue_reqs)
            last_metrics_time = now

        # Use server gen_throughput for live display; fall back to client-side estimate
        if state.srv_gen_throughput > 0:
            state.cell_live_tps = state.srv_gen_throughput
        elif measurement_start:
            client_elapsed = now - measurement_start
            measurement_tokens = shared_token_count[0] - measurement_tokens_start
            if client_elapsed > 0.5 and measurement_tokens > 0:
                state.cell_live_tps = measurement_tokens / client_elapsed

        # Update TUI
        live.update(build_display(state))

        # Check duration (measured from after warmup completes)
        measure_elapsed = (now - measurement_start) if measurement_start else 0
        if measurement_start and measure_elapsed >= duration:
            cancel_event.set()
            break

        # Check if all tasks already done
        if all(t.done() for t in tasks):
            break

    # Wait for tasks to finish (grace period)
    done, pending = await asyncio.wait(tasks, timeout=30.0)
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.wait(pending, timeout=5.0)

    # Collect results
    wall_time = time.monotonic() - state.cell_start
    stream_results = []
    for t in tasks:
        try:
            stream_results.append(t.result())
        except (asyncio.CancelledError, Exception):
            stream_results.append(StreamResult(error="cancelled", total_time=wall_time))

    # Final metrics scrape
    metrics = await scrape_metrics(client, base_url)
    if engine == ENGINE_SGLANG:
        final_gen_throughput = extract_metric(metrics, metric_name(engine, "gen_throughput"))
    else:
        final_gen_throughput = extract_metric(metrics, metric_name(engine, "gen_throughput"))
        if final_gen_throughput == 0 and prev_gen_tokens is not None:
            gen_total = extract_metric(metrics, metric_name(engine, "gen_tokens_total"))
            dt = time.monotonic() - prev_gen_time if prev_gen_time else 0
            if gen_total > 0 and dt > 0.1:
                final_gen_throughput = (gen_total - prev_gen_tokens) / dt
    if final_gen_throughput > 0:
        gen_throughput_samples.append(final_gen_throughput)

    # Use server-side gen_throughput as the primary metric (median for robustness)
    avg_gen_throughput = median(gen_throughput_samples) if gen_throughput_samples else 0.0

    # Client-side stats
    successful = [r for r in stream_results if r.error is None]
    total_tokens = sum(r.total_tokens for r in stream_results)

    # Client-side fallback: only when server metrics give 0 (vLLM V1 missing gauge
    # and counter not updating in real-time).
    # shared_token_count tracks exact token count (1 SSE chunk = 1 token).
    if avg_gen_throughput == 0:
        measure_duration = (time.monotonic() - measurement_start) if measurement_start else wall_time
        measurement_tokens = shared_token_count[0] - measurement_tokens_start
        if measure_duration > 0 and measurement_tokens > 0:
            avg_gen_throughput = measurement_tokens / measure_duration

    # Derive per-request from aggregate for consistency
    per_req_tps = avg_gen_throughput / concurrency if concurrency > 0 else 0.0
    ttfts = [r.ttft for r in successful if r.ttft > 0]

    # Queue stats
    avg_running = mean(running_reqs_samples) if running_reqs_samples else 0.0
    max_running = max(running_reqs_samples) if running_reqs_samples else 0
    avg_queue = mean(queue_reqs_samples) if queue_reqs_samples else 0.0
    max_queue = max(queue_reqs_samples) if queue_reqs_samples else 0
    queued_count = sum(1 for q in queue_reqs_samples if q > 0)
    queue_frac = queued_count / len(queue_reqs_samples) if queue_reqs_samples else 0.0

    cell = CellResult(
        concurrency=concurrency,
        context_tokens=context_tokens,
        aggregate_tps=avg_gen_throughput,
        per_request_avg_tps=per_req_tps,
        ttft_avg=mean(ttfts) if ttfts else 0.0,
        ttft_p50=percentile(ttfts, 50) if ttfts else 0.0,
        ttft_p99=percentile(ttfts, 99) if ttfts else 0.0,
        total_tokens=total_tokens,
        wall_time=wall_time,
        num_completed=len(successful),
        num_errors=len(stream_results) - len(successful),
        server_gen_throughput=median(gen_throughput_samples) if gen_throughput_samples else 0.0,
        server_utilization=extract_metric(metrics, metric_name(engine, "utilization")),
        server_spec_accept_rate=extract_metric(metrics, metric_name(engine, "spec_accept_rate")),
        avg_running_reqs=round(avg_running, 1),
        max_running_reqs=max_running,
        avg_queue_reqs=round(avg_queue, 1),
        max_queue_reqs=max_queue,
        queue_fraction=round(queue_frac, 3),
    )

    state.cell_running = False
    state.results[(context_tokens, concurrency)] = cell.aggregate_tps
    state.errors[(context_tokens, concurrency)] = cell.num_errors
    state.queue_info[(context_tokens, concurrency)] = (cell.avg_running_reqs, cell.avg_queue_reqs)

    await cell_client.aclose()
    return cell


# ---------------------------------------------------------------------------
# TUI rendering
# ---------------------------------------------------------------------------

def build_display(state: TUIState) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="middle", size=10),
        Layout(name="results", ratio=1, minimum_size=8),
        Layout(name="footer", size=3),
    )
    layout["middle"].split_row(
        Layout(name="current_test", ratio=1),
        Layout(name="server_metrics", ratio=1),
    )

    # Header
    header_text = Text()
    engine_label = state.engine.upper() if state.engine else "Benchmark"
    header_text.append(f"{engine_label} Benchmark", style="bold cyan")
    header_text.append(f"  {state.model_name} @ {state.server_url}")
    header_text.append(f"  |  {state.total_tests} tests  |  {state.cell_duration:.0f}s each")
    if state.kv_cache_budget > 0 or state.max_running_requests > 0:
        header_text.append("  |  ", style="dim")
        if state.kv_cache_budget > 0:
            header_text.append(f"KV: {state.kv_cache_budget:,}", style="cyan")
        if state.max_running_requests > 0:
            if state.kv_cache_budget > 0:
                header_text.append("  ", style="dim")
            header_text.append(f"MaxReqs: {state.max_running_requests}", style="cyan")
        if state.skipped_cells > 0:
            header_text.append(f"  ({state.skipped_cells} skipped)", style="yellow")
    layout["header"].update(Panel(header_text, style="bold"))

    # Current test panel
    if state.cell_running:
        elapsed = time.monotonic() - state.cell_start
        if state.prefill_phase:
            cell_text = (
                f"[bold magenta]PREFILL[/bold magenta]  ctx={format_context(state.current_context)}\n"
                f"  Elapsed: {elapsed:.1f}s\n"
                f"  Populating radix cache...\n"
                f"  Test [bold]{state.completed_tests + 1}[/bold] of {state.total_tests}"
            )
        else:
            if state.cell_warmup:
                # During ramp-up: show elapsed warmup time and why we're waiting
                if state.srv_gen_throughput == 0 and state.cell_tokens == 0:
                    wait_reason = "waiting for token generation (JIT compile?)"
                elif state.srv_queue_reqs > 0:
                    wait_reason = "waiting for queue→0 (prefill ramp-up)"
                elif hasattr(state, '_active_streams') and state._active_streams < state.current_concurrency:
                    wait_reason = f"waiting for all streams ({state._active_streams}/{state.current_concurrency})"
                else:
                    wait_reason = "stabilizing..."
                cell_text = (
                    f"[bold]DECODE[/bold]  C={state.current_concurrency}, ctx={format_context(state.current_context)}"
                    f"  [magenta]RAMP-UP[/magenta]\n"
                    f"  {wait_reason} {elapsed:.0f}s\n"
                    f"  Server: [bold yellow]{state.cell_live_tps:.1f}[/bold yellow] tok/s  "
                    f"running={state.srv_running_reqs} queue={state.srv_queue_reqs}\n"
                    f"  Test [bold]{state.completed_tests + 1}[/bold] of {state.total_tests}"
                )
            else:
                # Measurement phase: progress bar from measurement_start
                measure_elapsed = (time.monotonic() - state.cell_measurement_start) if state.cell_measurement_start > 0 else elapsed
                pct = min(measure_elapsed / state.cell_duration, 1.0) if state.cell_duration > 0 else 0
                bar_width = 30
                filled = int(pct * bar_width)
                bar = "[green]" + "=" * filled + ">" + "[/green]" + " " * (bar_width - filled - 1)

                cell_text = (
                    f"[bold]DECODE[/bold]  C={state.current_concurrency}, ctx={format_context(state.current_context)}\n"
                    f"  [{bar}] {measure_elapsed:.0f}/{state.cell_duration:.0f}s\n"
                    f"  Server: [bold yellow]{state.cell_live_tps:.1f}[/bold yellow] tok/s ({state.engine} throughput)\n"
                    f"  Test [bold]{state.completed_tests + 1}[/bold] of {state.total_tests}"
                )
    else:
        cell_text = "[dim]Waiting...[/dim]"
    layout["current_test"].update(Panel(cell_text, title="Current Test", border_style="cyan"))

    # Server metrics panel
    srv_table = Table(show_header=False, box=None, padding=(0, 1))
    srv_table.add_column("Metric", style="dim")
    srv_table.add_column("Value", style="bold")
    srv_table.add_row("gen_throughput", f"{state.srv_gen_throughput:.1f} tok/s")
    srv_table.add_row("running_reqs", str(state.srv_running_reqs))
    srv_table.add_row("queue_reqs", str(state.srv_queue_reqs))
    srv_table.add_row("utilization", f"{state.srv_utilization:.2%}")
    srv_table.add_row("spec_accept_rate", f"{state.srv_spec_accept_rate:.2%}")
    srv_table.add_row("spec_accept_len", f"{state.srv_spec_accept_length:.1f}")
    layout["server_metrics"].update(Panel(srv_table, title="Server Metrics", border_style="magenta"))

    # Results table
    results_table = Table(title="Aggregate Throughput (tok/s)", border_style="green", expand=True)
    results_table.add_column("ctx \\ conc", style="bold cyan", min_width=8)
    for conc in state.concurrency_levels:
        results_table.add_column(str(conc), justify="right", min_width=10)

    # Determine color thresholds from existing results (exclude skipped=-1)
    all_values = [v for v in state.results.values() if v > 0]
    if all_values:
        p25 = percentile(all_values, 25)
        p75 = percentile(all_values, 75)
    else:
        p25, p75 = 0, 0

    for ctx in state.context_lengths:
        row = [format_context(ctx)]
        for conc in state.concurrency_levels:
            key = (ctx, conc)
            if key in state.results:
                val = state.results[key]
                if val < 0:
                    needed = conc * (ctx + state.max_tokens)
                    row.append(f"[dim]N/A ({needed // 1024}k)[/dim]")
                    continue
                errs = state.errors.get(key, 0)
                if val > p75 and p75 > 0:
                    style = "bold green"
                elif val < p25 and p25 > 0:
                    style = "red"
                else:
                    style = "yellow"
                cell = f"{val:.1f}"
                if errs > 0:
                    cell += f" [red]({errs}e)[/red]"
                # Show running/requested when queuing detected
                qi = state.queue_info.get(key)
                if qi and qi[1] > 0:
                    avg_run, avg_q = qi
                    cell += f" [magenta]({avg_run:.0f}/{conc})[/magenta]"
                row.append(f"[{style}]{cell}[/{style}]")
            else:
                row.append("[dim]...[/dim]")
        results_table.add_row(*row)

    # Prefill table (shown alongside decode results)
    if state.prefill_contexts:
        prefill_table = Table(title="Prefill Speed (C=1)", border_style="magenta", expand=True)
        prefill_table.add_column("Context", style="bold cyan", min_width=6)
        prefill_table.add_column("TTFT", justify="right", min_width=6)
        prefill_table.add_column("Prefill", justify="right", min_width=6)
        prefill_table.add_column("tok/s", justify="right", min_width=8)
        # Cold vs warm are the numbers that actually discriminate a lazy-read
        # change; the blended tok/s column is kept for continuity with
        # existing result files and dashboards.
        prefill_table.add_column("cold", justify="right", min_width=8)
        prefill_table.add_column("warm", justify="right", min_width=8)
        for ctx in state.prefill_contexts:
            if ctx in state.prefill_results:
                pr = state.prefill_results[ctx]
                cold = pr.get("first_touch_tok_per_sec")
                warm = pr.get("warm_tok_per_sec")
                prefill_table.add_row(
                    format_context(ctx),
                    f"{pr['ttft']:.2f}s",
                    f"{pr.get('prefill_time', pr['ttft']):.2f}s",
                    f"[bold green]{pr['tok_per_sec']:,.0f}[/bold green]",
                    f"{cold:,.0f}" if cold is not None else "[dim]n/a[/dim]",
                    f"{warm:,.0f}" if warm is not None else "[dim]n/a[/dim]",
                )
            else:
                prefill_table.add_row(
                    format_context(ctx), "[dim]...[/dim]", "[dim]...[/dim]",
                    "[dim]...[/dim]", "[dim]...[/dim]", "[dim]...[/dim]",
                )

        results_layout = Layout()
        results_layout.split_row(
            Layout(Panel(prefill_table), ratio=1),
            Layout(Panel(results_table), ratio=3),
        )
        layout["results"].update(results_layout)
    else:
        layout["results"].update(Panel(results_table))

    # Footer - overall progress
    if state.total_tests > 0:
        overall_pct = state.completed_tests / state.total_tests
        elapsed_total = time.monotonic() - state.overall_start if state.overall_start > 0 else 0
        if state.cell_times:
            avg_cell = mean(state.cell_times)
            remaining = (state.total_tests - state.completed_tests) * avg_cell
            eta_str = format_time(remaining)
        else:
            eta_str = "calculating..."

        bar_width = 50
        filled = int(overall_pct * bar_width)
        bar = "[green]" + "=" * filled + ">" + "[/green]" + " " * max(0, bar_width - filled - 1)
        footer_text = (
            f"  [{bar}]  "
            f"{state.completed_tests}/{state.total_tests}  "
            f"Elapsed: {format_time(elapsed_total)}  "
            f"ETA: {eta_str}"
        )
    else:
        footer_text = "Initializing..."
    layout["footer"].update(Panel(footer_text, style="bold"))

    return layout


# ---------------------------------------------------------------------------
# Main benchmark loop
# ---------------------------------------------------------------------------

async def _detect_engine(check_client, base_url: str, model_ids: list, console, args):
    """Detect the inference engine from server endpoints. Mutates
    args.max_total_tokens (SGLang KV-budget auto-detect) and the module's
    server_context_length/max_running via return. Tries SGLang's
    /get_server_info, then vLLM's /version, then Ollama's /api/version, then
    a /metrics prefix sniff (vLLM else assumed SGLang)."""
    try:
        resp = await check_client.get(f"{base_url}/get_server_info", timeout=10.0)
        server_info = resp.json()
        if "max_total_num_tokens" not in server_info:
            raise ValueError("Not SGLang")
        engine = ENGINE_SGLANG
        console.print(f"[green]Engine: SGLang {server_info.get('version', '?')}[/green]  Models: {model_ids}")
        if args.max_total_tokens == 0:
            kv_budget = server_info.get("max_total_num_tokens", 0)
            if kv_budget:
                args.max_total_tokens = int(kv_budget)
                console.print(f"[cyan]KV cache budget:[/cyan] {args.max_total_tokens:,} tokens")
        max_running = server_info.get("max_running_requests")
        max_running = int(max_running) if max_running else None
        context_length = server_info.get("context_length")
        # Verify that --enable-metrics is active
        try:
            metrics_resp = await check_client.get(f"{base_url}/metrics", timeout=5.0)
            if "sglang:" not in metrics_resp.text[:2000]:
                console.print(
                    "[bold red]ERROR: SGLang server does not have metrics enabled.[/bold red]\n"
                    "This benchmark requires Prometheus metrics for accurate server-side throughput measurement.\n"
                    "Restart SGLang with [bold]--enable-metrics[/bold] flag.\n\n"
                    "Example:\n"
                    "  python -m sglang.launch_server --model ... --enable-metrics"
                )
                sys.exit(1)
        except httpx.HTTPError:
            console.print(
                "[bold red]ERROR: Cannot reach SGLang /metrics endpoint.[/bold red]\n"
                "Restart SGLang with [bold]--enable-metrics[/bold] flag."
            )
            sys.exit(1)
        return engine, max_running, context_length

    except Exception:
        # Not SGLang — try vLLM
        try:
            resp = await check_client.get(f"{base_url}/version", timeout=10.0)
            version_info = resp.json()
            if "version" not in version_info:
                raise ValueError("No version")
            engine = ENGINE_VLLM
            console.print(f"[green]Engine: vLLM {version_info['version']}[/green]  Models: {model_ids}")
            return engine, None, None
        except Exception:
            pass

        # Not vLLM — try Ollama (no SGLang/vLLM endpoints; /api/version is its
        # health+version signal)
        try:
            resp = await check_client.get(f"{base_url}/api/version", timeout=10.0)
            version_info = resp.json()
            if "version" not in version_info:
                raise ValueError("No version")
            engine = ENGINE_OLLAMA
            console.print(f"[green]Engine: Ollama {version_info['version']}[/green]  Models: {model_ids}")
            return engine, None, None
        except Exception:
            pass

        # Fallback: check /metrics prefix
        try:
            resp = await check_client.get(f"{base_url}/metrics", timeout=5.0)
            if "vllm:" in resp.text[:2000]:
                engine = ENGINE_VLLM
                console.print(f"[green]Engine: vLLM (detected from metrics)[/green]  Models: {model_ids}")
                return engine, None, None
            console.print(f"[green]Engine: SGLang (assumed)[/green]  Models: {model_ids}")
            return ENGINE_SGLANG, None, None
        except Exception:
            console.print(f"[yellow]Could not detect engine. Assuming SGLang.[/yellow]  Models: {model_ids}")
            return ENGINE_SGLANG, None, None


async def fetch_server_props(client: httpx.AsyncClient, base_url: str) -> Optional[dict]:
    """GET /props from the live target - llama-server's own self-report of
    its generation defaults, n_ctx, model path, chat template, and build
    version. A second, server-sourced fact set independent of whatever the
    orchestrator captured via docker inspect (and the only source at all
    when this script is run standalone, without an orchestrator). Not every
    engine implements /props (vLLM/SGLang/Ollama don't) - failure here is
    expected and must never abort the benchmark, so any error just means
    "not available", not a real problem."""
    try:
        resp = await client.get(f"{base_url}/props", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


async def run_benchmark(args):
    concurrency_levels = [int(x) for x in args.concurrency.split(",")]
    context_lengths = [int(x) for x in args.contexts.split(",")]
    base_url = f"http://{args.host}:{args.port}"
    console = Console()

    # --kv-budget overrides --max-total-tokens
    if args.kv_budget > 0:
        args.max_total_tokens = args.kv_budget
        console.print(f"[cyan]KV cache budget (manual):[/cyan] {args.max_total_tokens:,} tokens")

    # --- Step 1: Connect to server, detect engine, and read limits ---
    server_context_length = 0
    max_running = None
    engine = ENGINE_SGLANG
    server_props = None
    async with httpx.AsyncClient() as check_client:
        try:
            resp = await check_client.get(f"{base_url}/v1/models", timeout=10.0)
            models = resp.json()
            model_ids = [m['id'] for m in models.get('data', [])]
            # Auto-detect model name from server if using default
            if args.model == "Qwen3.5" and model_ids:
                args.model = model_ids[0]
            # Get max_model_len (works for both SGLang and vLLM)
            model_data = models.get("data", [])
            if model_data:
                server_context_length = model_data[0].get("max_model_len", 0) or 0
        except Exception as e:
            console.print(f"[red]Cannot connect to server at {base_url}: {e}[/red]")
            console.print("Make sure SGLang or vLLM is running and the port is correct.")
            return [], {}, engine, server_props

        server_props = await fetch_server_props(check_client, base_url)
        global _server_props
        _server_props = server_props

        # Detect engine: explicit --engine skips detection entirely; otherwise
        # try SGLang's /get_server_info first, then vLLM's /version, then
        # Ollama's /api/version, then fall back to the /metrics prefix sniff.
        if args.engine != ENGINE_AUTO:
            engine = args.engine
            console.print(f"[green]Engine: {engine} (explicit --engine)[/green]  Models: {model_ids}")
        else:
            engine, max_running, detected_context = await _detect_engine(
                check_client, base_url, model_ids, console, args
            )
            if detected_context:
                server_context_length = detected_context

        # vLLM: KV budget cannot be reliably derived from metrics (block_size includes
        # non-KV state for MoE/hybrid models). Rely on --kv-budget or queue detection.
        if engine == ENGINE_VLLM and args.max_total_tokens == 0:
            console.print(
                "[yellow]vLLM: KV cache budget not available from metrics. "
                "Use --kv-budget to skip over-capacity cells, or rely on queue detection.[/yellow]"
            )

        # Handle max_running_requests
        if max_running:
            over = [c for c in concurrency_levels if c > max_running]
            if over:
                concurrency_levels = [c for c in concurrency_levels if c <= max_running]
                console.print(f"[cyan]Max running requests:[/cyan] {max_running} (dropped C={','.join(str(c) for c in over)})")
        if server_context_length:
            console.print(f"[cyan]Model context length:[/cyan] {server_context_length:,} tokens")

    # --- Step 2: Build prefill context list (up to 200k or model limit) ---
    PREFILL_CANDIDATES = [8192, 16384, 32768, 65536, 131072]
    if args.prefill_contexts:
        prefill_contexts = [int(c) for c in args.prefill_contexts.split(",") if c.strip()]
        console.print(f"[cyan]Prefill contexts (explicit):[/cyan] {[format_context(c) for c in prefill_contexts]}")
    else:
        max_prefill = min(131072, server_context_length - 64) if server_context_length > 0 else 131072
        prefill_contexts = [c for c in PREFILL_CANDIDATES if c <= max_prefill]
        if not prefill_contexts and max_prefill > 0:
            prefill_contexts = [max_prefill]
        console.print(f"[cyan]Prefill tests:[/cyan] {[format_context(c) for c in prefill_contexts]}")

    # --- Step 3: Generate unique padding text per context length ---
    # Each context gets a unique prefix so radix cache cannot match across lengths.
    # Within same length, same text is reused → decode phase gets cache hit.
    #
    # Each context also gets its own *body*, not a truncated copy of one shared
    # base text. The old shared-base scheme made every longer context inherit
    # the pages an earlier, shorter context had already faulted in - i.e. it
    # measured a partly warm cache for exactly the cold-read cost under test,
    # on top of the repeated-filler problem. Deriving the body from
    # (padding seed, ctx) keeps runs reproducible while making each context's
    # text genuinely first-touch for the page cache.
    all_ctx_sizes = sorted(set(prefill_contexts + [c for c in context_lengths if c > 0]))
    max_ctx = max(all_ctx_sizes) if all_ctx_sizes else 0
    context_cache = {}
    run_id = ''.join(random.choices(string.ascii_lowercase, k=12))
    if max_ctx > 0:
        corpus = ""
        if args.context_file:
            try:
                with open(args.context_file, "r", errors="replace") as f:
                    corpus = f.read()
            except OSError as e:
                console.print(f"[red]--context-file unreadable ({e}); falling back to synthetic text[/red]")
                corpus = ""
            if corpus and len(corpus) < max_ctx * CHARS_PER_TOKEN:
                console.print(
                    f"[yellow]--context-file is shorter than the largest context "
                    f"({len(corpus):,} chars < {max_ctx * CHARS_PER_TOKEN:,}) - it will be "
                    f"tiled, which reintroduces the repetition this generator exists to "
                    f"avoid. Prefer a corpus at least that long.[/yellow]"
                )
            if corpus:
                console.print(f"[cyan]Using real corpus:[/cyan] {args.context_file} ({len(corpus):,} chars)")
        console.print(f"[bold]Generating padding texts (run={run_id}, up to {format_context(max_ctx)})...[/bold]")
        for ctx in all_ctx_sizes:
            # Unique prefix per run + context length → no cross-run or cross-length cache hits
            prefix = f"[BENCH_{run_id}_CTX_{ctx}] "
            target_chars = ctx * CHARS_PER_TOKEN
            if corpus:
                body = _corpus_slice(corpus, target_chars, f"{args.padding_seed}:{ctx}")
            else:
                body = generate_padding_text(ctx, seed=f"{args.padding_seed}:{ctx}")
            context_cache[ctx] = (prefix + body)[:target_chars]
    context_cache[0] = ""
    console.print("[green]Done.[/green]\n")

    # --- Step 4: Initialize TUI state ---
    state = TUIState(
        engine=engine,
        model_name=args.model,
        server_url=f"{args.host}:{args.port}",
        total_tests=len(concurrency_levels) * len(context_lengths),
        concurrency_levels=concurrency_levels,
        context_lengths=context_lengths,
        overall_start=time.monotonic(),
    )
    if max_running:
        state.max_running_requests = int(max_running)
    state.max_tokens = args.max_tokens
    state.prefill_contexts = prefill_contexts

    # Mark skipped decode cells
    if args.max_total_tokens > 0:
        state.kv_cache_budget = args.max_total_tokens
        runnable = sum(
            1 for ctx in context_lengths for conc in concurrency_levels
            if conc * (ctx + args.max_tokens) <= args.max_total_tokens
        )
        skipped = state.total_tests - runnable
        state.skipped_cells = skipped
        for ctx in context_lengths:
            for conc in concurrency_levels:
                if conc * (ctx + args.max_tokens) > args.max_total_tokens:
                    state.results[(ctx, conc)] = -1

    # Add prefill tests to total count (unless skipped)
    if args.skip_prefill:
        prefill_contexts = []
        state.prefill_contexts = []
    state.total_tests += len(prefill_contexts)

    # Run benchmark
    global _partial_results
    all_results = []
    max_conc = max(concurrency_levels)
    limits = httpx.Limits(max_connections=max_conc + 20, max_keepalive_connections=max_conc + 10)

    async def measure_ttft(client, messages):
        """Send one streaming request with max_tokens=1, return TTFT in seconds."""
        payload = {
            "model": args.model,
            "messages": messages,
            "stream": True,
            "max_tokens": 1,
        }
        t0 = time.monotonic()
        try:
            async with client.stream(
                "POST", f"{base_url}/v1/chat/completions",
                json=payload,
                timeout=httpx.Timeout(args.prefill_timeout, connect=30.0),
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    if "choices" in data and len(data["choices"]) > 0:
                        delta = data["choices"][0].get("delta", {})
                        if delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content"):
                            return time.monotonic() - t0
        except Exception:
            pass
        return time.monotonic() - t0

    async def measure_prefill_server(client, messages):
        """Authoritative prefill measurement for llama.cpp-family servers.

        Returns dict(prompt_tokens, seconds, tok_per_sec, cached_tokens) or
        None when the server reports no `timings` block (SGLang/vLLM/Ollama).

        This exists because the TTFT path divides the *requested* context by
        the measured time, which silently assumes CHARS_PER_TOKEN holds for
        the text in use. It does not: measured against the live server,
        synthetic prose came out at 5.84 chars/token but this repo's own
        source at 2.61, so a "16384-token" request was really 11,230 tokens
        of one text and 25,079 of the other. Reporting a rate against the
        requested number made the two incomparable, wrong by up to 2.2x.

        `cache_prompt: false` forces the server to reprocess the whole
        prompt, so `prompt_n` is the real prefill and `cache_n` should be 0 -
        without it a repeat of the same prefix scores as a ~0-token prefill
        at a meaningless rate.
        """
        payload = {
            "model": args.model,
            "messages": messages,
            "max_tokens": 1,
            "stream": False,
            "cache_prompt": False,
        }
        try:
            resp = await client.post(
                f"{base_url}/v1/chat/completions", json=payload,
                timeout=httpx.Timeout(args.prefill_timeout, connect=30.0),
            )
            data = resp.json()
        except Exception:
            return None
        timings = data.get("timings")
        if not isinstance(timings, dict):
            return None
        prompt_n = timings.get("prompt_n") or 0
        prompt_ms = timings.get("prompt_ms") or 0
        if prompt_n <= 0 or prompt_ms <= 0:
            return None
        seconds = prompt_ms / 1000.0
        return {
            "prompt_tokens": prompt_n,
            "cached_tokens": timings.get("cache_n") or 0,
            "usage_prompt_tokens": (data.get("usage") or {}).get("prompt_tokens") or 0,
            "seconds": seconds,
            "tok_per_sec": timings.get("prompt_per_second") or (prompt_n / seconds),
        }

    async with httpx.AsyncClient(limits=limits) as client:
        with Live(build_display(state), refresh_per_second=2, console=console) as live:

            # === Phase 1: Prefill benchmark (C=1, max_tokens=1) ===
            if prefill_contexts:
                # Warmup: trigger CUDA graph compilation before measurements.
                state.prefill_phase = True
                state.current_context = 0
                state.cell_running = True
                state.cell_start = time.monotonic()
                live.update(build_display(state))

                # Warmup 1: short decode (triggers decode CUDA graphs / JIT compilation)
                warmup_payload = {
                    "model": args.model,
                    "messages": [{"role": "user", "content": "Count from 1 to 20."}],
                    "stream": True, "max_tokens": 64,
                }
                try:
                    async with client.stream(
                        "POST", f"{base_url}/v1/chat/completions",
                        json=warmup_payload,
                        timeout=httpx.Timeout(300.0, connect=30.0),
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if line and line.startswith("data: [DONE]"):
                                break
                except Exception:
                    pass

                # Warmup 2: prefill with smallest test context (triggers prefill CUDA graphs)
                #
                # Deliberately NOT the real context_cache text for this size:
                # warming with the measured text would make the smallest
                # context's first-touch sample warm, defeating the cold
                # measurement at exactly the size that is cheapest to re-run
                # cold. Same token count, different body.
                #
                # Capped, because the prefill contexts can be very large. The
                # only job left here is triggering prefill graph/JIT
                # compilation, and llama.cpp builds graphs per ubatch shape, so
                # a few thousand tokens is enough. Uncapped, a 256k prefill
                # context made this warmup a *second* full 256k prefill -
                # measured 2026-09-27 at 1768s on its own, roughly doubling the
                # prefill phase for nothing.
                warmup_ctx = min(prefill_contexts[0], WARMUP_MAX_CTX)
                warmup_prefix = f"[WARMUP_{run_id}] "
                warmup_text = warmup_prefix + generate_padding_text(
                    warmup_ctx, seed=f"{args.padding_seed}:warmup"
                )
                warmup_text = warmup_text[:warmup_ctx * CHARS_PER_TOKEN]
                warmup_msgs = build_messages(warmup_ctx, warmup_text)
                await measure_ttft(client, warmup_msgs)

                # Measure baseline TTFT (ctx=0) to subtract overhead
                baseline_msgs = [{"role": "user", "content": "Say OK."}]
                baseline_samples = []
                for _ in range(5):
                    t = await measure_ttft(client, baseline_msgs)
                    baseline_samples.append(t)
                baseline_ttft = median(baseline_samples)
                state.cell_running = False

                # Now measure each prefill context
                REPEAT_THRESHOLD = 8192

                for ctx in prefill_contexts:
                    state.current_concurrency = 1
                    state.current_context = ctx
                    state.cell_running = True
                    state.cell_start = time.monotonic()
                    state.cell_duration = 0
                    live.update(build_display(state))

                    # First sample is first-touch for this context's own text
                    # (cold page cache); the rest are warm re-prefills of the
                    # same token count. Both are recorded: the lazy-read /
                    # on-direct change this harness exists to evaluate is
                    # specifically a *cold* win that is near-flat cold-to-warm,
                    # so a single blended number hides it either way. The old
                    # `repeats = 1` for ctx >= 8192 reported a cold number with
                    # no warm comparison at all.
                    repeats = args.prefill_repeats if args.prefill_repeats > 0 else (3 if ctx < REPEAT_THRESHOLD else 2)
                    repeats = max(repeats, 1)
                    ttft_samples = []
                    server_samples = []
                    for r in range(repeats):
                        if r == 0:
                            msgs = build_messages(ctx, context_cache[ctx])
                        else:
                            prefix = f"[BENCH_{run_id}_CTX_{ctx}_R{r}] "
                            orig_prefix_len = len(f"[BENCH_{run_id}_CTX_{ctx}] ")
                            variant_text = prefix + context_cache[ctx][orig_prefix_len:]
                            msgs = build_messages(ctx, variant_text)
                        s = await measure_prefill_server(client, msgs)
                        if s is not None:
                            server_samples.append(s)
                        else:
                            ttft_samples.append(await measure_ttft(client, msgs))

                    if server_samples:
                        # Preferred: the server reported real prompt token
                        # counts, so the rate is correct for whatever text is
                        # in use instead of assuming CHARS_PER_TOKEN.
                        rates = [s["tok_per_sec"] for s in server_samples]
                        times = [s["seconds"] for s in server_samples]
                        tok_per_sec = median(rates)
                        prefill_time = median(times)
                        raw_ttft = prefill_time
                        first_touch_tok_per_sec = server_samples[0]["tok_per_sec"]
                        first_touch_ttft = server_samples[0]["seconds"]
                        warm_tok_per_sec = median(rates[1:]) if len(rates) > 1 else None
                        warm_ttft = median(times[1:]) if len(times) > 1 else None
                        prompt_tokens = server_samples[0]["prompt_tokens"]
                        cached_tokens = max(s["cached_tokens"] for s in server_samples)
                        usage_prompt_tokens = server_samples[0]["usage_prompt_tokens"]
                        tok_basis = "server"
                        n_samples = len(server_samples)
                    else:
                        # Fallback (SGLang/vLLM/Ollama): no timings block, so
                        # the requested context stands in for the token count.
                        # `tok_basis` records that, because it is wrong by up
                        # to ~2x for token-dense text.
                        raw_ttft = median(ttft_samples)
                        prefill_time = max(raw_ttft - baseline_ttft, 0.001)
                        tok_per_sec = ctx / prefill_time
                        first_touch_ttft = ttft_samples[0]
                        first_touch_tok_per_sec = ctx / max(first_touch_ttft - baseline_ttft, 0.001)
                        if len(ttft_samples) > 1:
                            warm_ttft = median(ttft_samples[1:])
                            warm_tok_per_sec = ctx / max(warm_ttft - baseline_ttft, 0.001)
                        else:
                            warm_ttft = None
                            warm_tok_per_sec = None
                        prompt_tokens = 0
                        cached_tokens = 0
                        usage_prompt_tokens = 0
                        tok_basis = "requested-ctx"
                        n_samples = len(ttft_samples)

                    state.prefill_results[ctx] = {
                        "ttft": raw_ttft,
                        "prefill_time": prefill_time,
                        "tok_per_sec": tok_per_sec,
                        "baseline": baseline_ttft,
                        # Additive cold/warm split - see the repeats comment.
                        "samples": n_samples,
                        "first_touch_ttft": first_touch_ttft,
                        "first_touch_tok_per_sec": first_touch_tok_per_sec,
                        "warm_ttft": warm_ttft,
                        "warm_tok_per_sec": warm_tok_per_sec,
                        # Real prompt token count + which basis the rate is on.
                        "prompt_tokens": prompt_tokens,
                        "cached_tokens": cached_tokens,
                        "usage_prompt_tokens": usage_prompt_tokens,
                        "tok_basis": tok_basis,
                        # What the *text* was, not just how long: the PLE
                        # table is keyed on 3-grams, so this is the coverage
                        # that decides whether a prefill number is measuring
                        # that table at all.
                        **trigram_stats(context_cache[ctx]),
                    }

                    state.cell_running = False
                    state.completed_tests += 1
                    cell_time = time.monotonic() - state.cell_start
                    state.cell_times.append(cell_time)
                    live.update(build_display(state))
                    await asyncio.sleep(1.0)

                # Re-cache the primary text for decode phase (repeat runs used variants)
                for ctx in prefill_contexts:
                    if ctx < REPEAT_THRESHOLD:
                        msgs = build_messages(ctx, context_cache[ctx])
                        await measure_ttft(client, msgs)

            # Warm radix cache for decode contexts not already tested in prefill
            for ctx in context_lengths:
                if ctx > 0 and ctx not in prefill_contexts:
                    warmup_msgs = build_messages(ctx, context_cache[ctx])
                    warmup_payload = {
                        "model": args.model, "messages": warmup_msgs,
                        "stream": False, "max_tokens": 1,
                    }
                    try:
                        await client.post(
                            f"{base_url}/v1/chat/completions",
                            json=warmup_payload,
                            # Full-context request: the same timeout the
                            # prefill phase needs, not a fixed 600s.
                            timeout=httpx.Timeout(args.prefill_timeout, connect=30.0),
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)

            # === Phase 2: Decode benchmark (cached prefill, pure decode speed) ===
            state.prefill_phase = False
            for ctx in context_lengths:
                for conc in concurrency_levels:
                    # Skip cells that exceed token budget
                    cell_total = conc * (ctx + args.max_tokens)
                    if args.max_total_tokens > 0 and cell_total > args.max_total_tokens:
                        state.results[(ctx, conc)] = -1  # mark as skipped
                        cell = CellResult(concurrency=conc, context_tokens=ctx, aggregate_tps=-1)
                        all_results.append(cell)
                        _partial_results = all_results
                        state.completed_tests += 1
                        live.update(build_display(state))
                        continue

                    cell_start = time.monotonic()

                    try:
                        result = await run_one_cell(
                            client=client,
                            base_url=base_url,
                            concurrency=conc,
                            context_tokens=ctx,
                            context_text=context_cache[ctx],
                            duration=args.duration,
                            max_tokens=args.max_tokens,
                            model=args.model,
                            state=state,
                            live=live,
                            engine=engine,
                        )
                        all_results.append(result)
                        _partial_results = all_results
                    except Exception as e:
                        console.print(f"[red]Cell C={conc} ctx={format_context(ctx)} failed: {e}[/red]")
                        cell = CellResult(concurrency=conc, context_tokens=ctx)
                        all_results.append(cell)
                        _partial_results = all_results
                        state.results[(ctx, conc)] = 0.0
                        state.errors[(ctx, conc)] = conc

                    cell_time = time.monotonic() - cell_start
                    state.cell_times.append(cell_time)
                    state.completed_tests += 1
                    live.update(build_display(state))

                    # Brief pause between cells to let server settle
                    await asyncio.sleep(2.0)

    return all_results, state.prefill_results, engine, server_props


# ---------------------------------------------------------------------------
# Results output
# ---------------------------------------------------------------------------

def print_final_results(results: list, concurrency_levels: list, context_lengths: list,
                        console: Console, prefill_results: dict = None):
    console.print("\n")

    # Prefill table
    if prefill_results:
        baseline = next(iter(prefill_results.values()), {}).get("baseline", 0)
        pt = Table(title=f"Prefill Speed (C=1, baseline TTFT={baseline:.3f}s subtracted)",
                   border_style="magenta")
        pt.add_column("ctx", style="bold cyan")
        # Real prompt token count as the server counted it. The "ctx" column is
        # what was *requested*; when tok_basis is "requested-ctx" these differ
        # and the rate is only as good as the text's actual tokens-per-char
        # (see measure_prefill_server).
        pt.add_column("tokens", justify="right")
        pt.add_column("basis", justify="right")
        pt.add_column("ttft s", justify="right")
        pt.add_column("prefill s", justify="right")
        pt.add_column("tok/s", justify="right")
        # Cold (first-touch) vs warm (repeat) - the columns that actually
        # discriminate a lazy-read change. `tok/s` remains the blended headline
        # for continuity with existing result files.
        pt.add_column("cold", justify="right")
        pt.add_column("warm", justify="right")
        # Distinct 3-grams in the prompt: whether this result measured the
        # PLE/ngram table at all. A periodic prompt pins this; real text grows
        # it. Two runs with the same "tokens" column and wildly different
        # values here are not comparable.
        pt.add_column("3g dist", justify="right")
        for ctx in sorted(prefill_results.keys()):
            pr = prefill_results[ctx]
            cold = pr.get("first_touch_tok_per_sec")
            warm = pr.get("warm_tok_per_sec")
            tokens = pr.get("prompt_tokens") or 0
            tg = pr.get("trigram_distinct")
            pt.add_row(
                format_context(ctx),
                f"{tokens:,}" if tokens else "?",
                pr.get("tok_basis", "?"),
                f"{pr['ttft']:.2f}",
                f"{pr.get('prefill_time', pr['ttft']):.2f}",
                f"{pr['tok_per_sec']:,.0f}",
                f"{cold:,.0f}" if cold is not None else "n/a",
                f"{warm:,.0f}" if warm is not None else "n/a",
                f"{tg:,}" if tg is not None else "?",
            )
        console.print(pt)
        console.print()

    # Aggregate throughput table
    table = Table(title="Aggregate Throughput (tok/s)", border_style="green")
    table.add_column("ctx \\ conc", style="bold cyan")
    for conc in concurrency_levels:
        table.add_column(str(conc), justify="right")

    result_map = {(r.context_tokens, r.concurrency): r for r in results}
    any_queued = any(r.avg_queue_reqs > 0 for r in results if r.aggregate_tps >= 0)

    for ctx in context_lengths:
        row = [format_context(ctx)]
        for conc in concurrency_levels:
            r = result_map.get((ctx, conc))
            if r and r.aggregate_tps < 0:
                row.append("skip")
            elif r:
                val = f"{r.aggregate_tps:.1f}"
                if r.num_errors > 0:
                    val += f" ({r.num_errors}e)"
                if r.avg_queue_reqs > 0:
                    val += f" ({r.avg_running_reqs:.0f}/{conc})"
                row.append(val)
            else:
                row.append("-")
        table.add_row(*row)

    console.print(table)
    if any_queued:
        console.print("[dim](X/Y) = avg running / requested concurrency — requests were queued[/dim]")

    # Per-request avg tok/s table
    table2 = Table(title="Per-Request Avg Throughput (tok/s)", border_style="blue")
    table2.add_column("ctx \\ conc", style="bold cyan")
    for conc in concurrency_levels:
        table2.add_column(str(conc), justify="right")

    for ctx in context_lengths:
        row = [format_context(ctx)]
        for conc in concurrency_levels:
            r = result_map.get((ctx, conc))
            if r and r.aggregate_tps < 0:
                row.append("skip")
            elif r and r.per_request_avg_tps > 0:
                val = f"{r.per_request_avg_tps:.1f}"
                if r.avg_queue_reqs > 0:
                    val += f" ({r.avg_running_reqs:.0f}/{conc})"
                row.append(val)
            else:
                row.append("-")
        table2.add_row(*row)

    console.print(table2)

    # TTFT table
    table3 = Table(title="Avg TTFT (seconds)", border_style="yellow")
    table3.add_column("ctx \\ conc", style="bold cyan")
    for conc in concurrency_levels:
        table3.add_column(str(conc), justify="right")

    for ctx in context_lengths:
        row = [format_context(ctx)]
        for conc in concurrency_levels:
            r = result_map.get((ctx, conc))
            if r and r.aggregate_tps < 0:
                row.append("skip")
            elif r and r.ttft_avg > 0:
                row.append(f"{r.ttft_avg:.2f}")
            else:
                row.append("-")
        table3.add_row(*row)

    console.print(table3)


def save_results(results: list, args, filepath: str, prefill_results: dict = None, engine: str = "",
                  server_props: Optional[dict] = None):
    concurrency_levels = [int(x) for x in args.concurrency.split(",")]
    context_lengths = [int(x) for x in args.contexts.split(",")]

    # Build summary table (exclude skipped)
    summary = {}
    actual_results = [r for r in results if r.aggregate_tps >= 0]
    for r in actual_results:
        ctx_key = str(r.context_tokens)
        if ctx_key not in summary:
            summary[ctx_key] = {}
        summary[ctx_key][str(r.concurrency)] = r.aggregate_tps

    # Prefill summary
    prefill_summary = {}
    if prefill_results:
        for ctx, pr in sorted(prefill_results.items()):
            entry = {
                "ttft_seconds": round(pr["ttft"], 3),
                "tok_per_sec": round(pr["tok_per_sec"], 0),
            }
            # Additive cold/warm split: `tok_per_sec` stays the blended
            # headline (so existing consumers keep working), while
            # first_touch_* is the cold number and warm_* the repeat number.
            if "first_touch_tok_per_sec" in pr:
                entry["first_touch_tok_per_sec"] = round(pr["first_touch_tok_per_sec"], 0)
                entry["first_touch_ttft_seconds"] = round(pr["first_touch_ttft"], 3)
                entry["samples"] = pr.get("samples", 1)
            if pr.get("warm_tok_per_sec") is not None:
                entry["warm_tok_per_sec"] = round(pr["warm_tok_per_sec"], 0)
                entry["warm_ttft_seconds"] = round(pr["warm_ttft"], 3)
            # Real prompt token count and the basis the rate is on. On
            # "server" these come from the server's own timings; on
            # "requested-ctx" the token count is unknown and the rate assumed
            # CHARS_PER_TOKEN, which is wrong by up to ~2x for dense text.
            if pr.get("prompt_tokens"):
                entry["prompt_tokens"] = pr["prompt_tokens"]
                entry["cached_tokens"] = pr.get("cached_tokens", 0)
            entry["tok_basis"] = pr.get("tok_basis", "requested-ctx")
            # Text coverage, so a result states whether it exercised the
            # 3-gram/PLE table at all.
            if "trigram_distinct" in pr:
                entry["trigram_distinct"] = pr["trigram_distinct"]
                entry["trigram_total"] = pr["trigram_total"]
                entry["trigram_distinct_ratio"] = pr["trigram_distinct_ratio"]
            prefill_summary[str(ctx)] = entry

    # target_launch_config: written by the orchestrator (docker inspect +
    # git rev-parse at the moment it started this benchmark's target - see
    # orchestrator.py's _capture_launch_config) and handed to us as a file
    # path, because the orchestrator is the only thing that knows what it
    # actually launched. This script's only job is reading that file and
    # putting its contents in the result, verbatim - never hand-edited.
    # Absent (None) when this script is run standalone, without an
    # orchestrator - that's expected, not an error.
    target_launch_config = None
    launch_config_path = getattr(args, "launch_config", "") or ""
    if launch_config_path:
        try:
            with open(launch_config_path) as f:
                target_launch_config = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            target_launch_config = {"error": f"could not read --launch-config {launch_config_path}: {e}"}

    output = {
        "schema_version": 2,
        "metadata": {
            "engine": engine,
            "model": args.model,
            "server": f"{args.host}:{args.port}",
            "timestamp": datetime.now().isoformat(),
            "duration_per_test": args.duration,
            "max_tokens": args.max_tokens,
            "max_total_tokens": args.max_total_tokens,
            "concurrency_levels": concurrency_levels,
            "context_lengths": context_lengths,
        },
        # bench_tool_commit: the exact git commit of the llm-inference-bench
        # tool that PRODUCED this result (as opposed to target_launch_config's
        # build_repo_commit, which is the commit the TARGET's compose file
        # came from - the two are usually the same commit since both live in
        # this repo, but can differ if the deployed image lags a builds/-only
        # push). Baked in at image-build time by the CI workflow via
        # --build-arg GIT_SHA - see Dockerfile/BENCH_GIT_SHA. None if run
        # from a non-CI-built image (e.g. a manual local build).
        "bench_tool_commit": os.environ.get("BENCH_GIT_SHA") or None,
        "target_launch_config": target_launch_config,
        "server_props": server_props,
        "prefill": prefill_summary,
        "results": [asdict(r) for r in actual_results],
        "summary_table": summary,
    }

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="LLM Inference Benchmark with Rich TUI Dashboard (SGLang + vLLM)"
    )
    parser.add_argument("--host", default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--port", type=int, default=5000, help="Server port (default: 5000)")
    parser.add_argument(
        "--concurrency", default="1,2,4,8,16,32,64,128",
        help="Comma-separated concurrency levels (default: 1,2,4,8,16,32,64,128)"
    )
    parser.add_argument(
        "--contexts", default="0,16384,32768,65536,131072",
        help="Comma-separated context lengths in tokens (default: 0,16384,32768,65536,131072)"
    )
    parser.add_argument(
        "--duration", type=float, default=30.0,
        help="Duration per test cell in seconds (default: 30)"
    )
    parser.add_argument(
        "--max-tokens", type=int, default=8192,
        help="Max tokens to generate per request (default: 8192)"
    )
    parser.add_argument(
        "--output", default="benchmark_results.json",
        help="Output JSON file path (default: benchmark_results.json)"
    )
    parser.add_argument(
        "--model", default="Qwen3.5",
        help="Model name for API requests (default: Qwen3.5)"
    )
    parser.add_argument(
        "--max-total-tokens", type=int, default=0,
        help="Max total tokens budget (concurrency × (context + max_tokens)). "
             "Cells exceeding this are skipped. 0 = no limit (default: 0)"
    )
    parser.add_argument(
        "--kv-budget", type=int, default=0,
        help="KV cache budget in tokens. Overrides auto-detection. "
             "Cells where concurrency × (context + max_tokens) > budget are skipped. "
             "Use this for vLLM where auto-detection is unreliable. (default: 0 = auto-detect)"
    )
    parser.add_argument(
        "--skip-prefill", action="store_true",
        help="Skip the prefill benchmark phase (Phase 1) and go straight to decode tests"
    )
    parser.add_argument(
        "--prefill-contexts", default="",
        help="Comma-separated prefill context sizes to benchmark (e.g. '8192,16384,32768'). "
             "Empty = auto (all candidates up to 128k or server limit). Use to cap the prefill "
             "phase for slow engines like Ollama so the run fits the build timeout."
    )
    parser.add_argument(
        "--prefill-repeats", type=int, default=0,
        help="Samples per prefill context. Sample 0 is first-touch (cold page cache), "
             "later samples are warm re-prefills; both are reported. 0 = default "
             "(3 below 8k, else 2). Set 1 to restore the old single-cold-sample "
             "behaviour at the cost of losing the cold/warm comparison."
    )
    parser.add_argument(
        "--prefill-timeout", type=float, default=7200.0, metavar="SECONDS",
        help="Read timeout for a single prefill request (default: 7200). Must cover the "
             "slowest request in the matrix or the measurement silently degrades: a "
             "250k-token prefill measured 1768s on this box on 2026-09-27, so the old "
             "hardcoded 1800s left ~2%% of margin and the 600s TTFT fallback could not "
             "cover it at all."
    )
    parser.add_argument(
        "--padding-seed", default="bench",
        help="Seed for synthetic padding text. Same seed + context length produces "
             "byte-identical text, so two builds can be A/B'd on identical input "
             "(default: bench)."
    )
    parser.add_argument(
        "--context-file", default="",
        help="Read padding text from this file instead of synthesising it. Real text "
             "is the authoritative input for lazy-read / cold-prefill work: synthetic "
             "prose has a fixed vocabulary and plateaus well below the distinct-trigram "
             "count real prompts reach. Each context length takes its own seeded window "
             "into the file, so contexts are not prefixes of one another. The file must "
             "already be visible inside whatever runs this script (mounted into the "
             "bench container, or a local path standalone)."
    )
    parser.add_argument(
        "--engine", default=ENGINE_AUTO, choices=[ENGINE_AUTO, ENGINE_SGLANG, ENGINE_VLLM, ENGINE_OLLAMA],
        help="Inference engine (default: auto-detect). Use 'ollama' for Ollama servers, "
             "which expose no SGLang/vLLM detection endpoints."
    )
    parser.add_argument(
        "--launch-config", default="", metavar="PATH",
        help="Path to a JSON file (written by the orchestrator via docker inspect + "
             "git rev-parse at launch time) describing exactly how the target server "
             "was started - image, resolved command, env, git commit. Embedded verbatim "
             "into the output under target_launch_config for reproducibility. Optional - "
             "omitted when running this script standalone, without an orchestrator."
    )
    return parser.parse_args()


_partial_results: list = []
_prefill_results: dict = {}
_server_props: Optional[dict] = None


def main():
    global _partial_results, _prefill_results, _server_props
    args = parse_args()
    console = Console()

    concurrency_levels = [int(x) for x in args.concurrency.split(",")]
    context_lengths = [int(x) for x in args.contexts.split(",")]
    decode_count = len(concurrency_levels) * len(context_lengths)

    console.print(Panel(
        f"[bold cyan]LLM Inference Benchmark[/bold cyan]\n"
        f"Model: {args.model} @ {args.host}:{args.port}\n"
        f"Decode concurrency: {concurrency_levels}\n"
        f"Decode contexts: {[format_context(c) for c in context_lengths]}\n"
        f"Duration: {args.duration}s per decode test | Max tokens: {args.max_tokens}\n"
        f"Phase 1: prefill (auto, up to 128k) | Phase 2: {decode_count} decode tests (cached)",
        title="Configuration",
        border_style="cyan",
    ))

    engine = ""
    try:
        results, prefill_results, engine, server_props = asyncio.run(run_benchmark(args))
        _prefill_results = prefill_results
        _server_props = server_props
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Saving partial results...[/yellow]")
        results = _partial_results
        prefill_results = _prefill_results
        server_props = _server_props

    if results or prefill_results:
        print_final_results(results, concurrency_levels, context_lengths, console, prefill_results)
        save_results(results, args, args.output, prefill_results, engine=engine, server_props=server_props)
        console.print(f"\n[green]Results saved to {args.output}[/green]")
    else:
        console.print("[red]No results collected.[/red]")


if __name__ == "__main__":
    main()
