#!/usr/bin/env python3
"""Generate the interactive model comparison dashboard.

Reads the new build stack under builds/ and emits a self-contained
interactive HTML page to docs/interactive-dashboard.html.

Data sources per build:
  builds/<name>/build.yaml                              derived metadata + status
  builds/<name>/docker-compose.yaml                     the build's compose def
  builds/<name>/benchmarks/llm-inference-bench/*.json   llm-inference-bench results

Multi-GPU: builds/<name>/build.yaml has no `target_gpu` field at all --
this legacy build stack (distinct from catalog/builds/*.yaml, which has
the field on every benchmark_runs[] entry) predates the R9700 entirely.
gpu_of() below reads `derived.target_gpu` if a future build.yaml ever adds
one, defaulting to DEFAULT_TARGET_GPU (strix-apu) otherwise -- same
default-with-no-guessing convention scripts/benchmark_orchestrator.py uses
for catalog/builds/*.yaml entries missing the field, so a reader never has
to wonder whether the GPU column was simply skipped for these builds.

Usage:
  python3 scripts/generate_interactive_dashboard.py [-o docs/interactive-dashboard.html]
"""

import argparse
import datetime
import glob
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDS_DIR = os.path.join(ROOT, "builds")
TEMPLATE = os.path.join(ROOT, "scripts", "dashboard_template.html")
DEFAULT_OUT = os.path.join(ROOT, "docs", "interactive-dashboard.html")

ENGINE_CAT = {
    "vllm-therock-gfx1151-v1": "vllm",
    "ollama-vulkan-0177-v1": "ollama",
    "ollama-rocm-0177-broken": "ollama",
    "ds4-strix-halo-v1": "ds4",
}
ENGINE_LABEL = {
    "vllm": "vLLM",
    "llamacpp": "llama.cpp",
    "ollama": "Ollama",
    "ds4": "DS4",
    "unknown": "unknown",
}
ENGINE_COLOR = {
    "vllm": "#5b9dff",
    "llamacpp": "#34d399",
    "ollama": "#fb923c",
    "ds4": "#a78bfa",
    "unknown": "#9aa4b2",
}

# catalog/hardware.yaml GPU ids -> dashboard label/color, same keying
# convention as ENGINE_LABEL/ENGINE_COLOR above so the client-side template
# treats GPU exactly like engine family -- one more built-in filter/legend
# dimension, not a bolted-on afterthought.
DEFAULT_TARGET_GPU = "strix-apu"
GPU_LABEL = {
    "r9700-egpu-dock": "R9700",
    "strix-apu": "Strix APU",
    "unknown": "unknown GPU",
}
GPU_COLOR = {
    "r9700-egpu-dock": "#a78bfa",
    "strix-apu": "#34d399",
    "unknown": "#9aa4b2",
}


def gpu_of(derived):
    """Resolve a build's target_gpu the same default-with-no-guessing way
    scripts/benchmark_orchestrator.py resolves catalog/builds/*.yaml's
    version-level target_gpu: read it if present (a future build.yaml
    could add one), else default to DEFAULT_TARGET_GPU (strix-apu) --
    every build.yaml in builds/ predates the R9700, so this default is
    factually correct for 100% of today's data, not a guess."""
    return derived.get("target_gpu") or DEFAULT_TARGET_GPU


def engine_cat(engine_ref):
    if engine_ref in ENGINE_CAT:
        return ENGINE_CAT[engine_ref]
    if engine_ref and "llamacpp" in engine_ref:
        return "llamacpp"
    if engine_ref and "vllm" in engine_ref:
        return "vllm"
    if engine_ref and "ollama" in engine_ref:
        return "ollama"
    return "unknown"


def model_key(model_display):
    return re.sub(r"\s*\(.*?\)\s*", "", model_display).strip()


def parse_params(s):
    if not s:
        return None
    m = re.search(r"([\d.]+)", str(s))
    return float(m.group(1)) if m else None


def arch_of(derived):
    p = parse_params(derived.get("params"))
    a = parse_params(derived.get("active_params"))
    if p is None:
        return "unknown"
    if a is not None and a < p:
        return "moe"
    return "dense"


def best_json(dirpath):
    files = sorted(glob.glob(os.path.join(dirpath, "benchmarks", "llm-inference-bench", "*.json")))
    if not files:
        return None, None
    best, best_score = None, (-1, None)
    for f in files:
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        results = data.get("results") or []
        score = sum(
            1 for r in results
            if r.get("num_completed", 0) > 0 and r.get("aggregate_tps", 0) > 0
        )
        ts = data.get("metadata", {}).get("timestamp", os.path.basename(f))
        if score > best_score[0] or (score == best_score[0] and ts > (best_score[1] or "")):
            best_score = (score, ts)
            best = f
    if best is None:
        return None, None
    with open(best) as fh:
        return json.load(fh), best


def load_builds():
    builds = []
    for bdir in sorted(glob.glob(os.path.join(BUILDS_DIR, "*"))):
        if not os.path.isdir(bdir):
            continue
        by_path = os.path.join(bdir, "build.yaml")
        compose_path = os.path.join(bdir, "docker-compose.yaml")
        if not os.path.exists(by_path) or not os.path.exists(compose_path):
            continue
        with open(by_path) as fh:
            by = yaml.safe_load(fh) or {}
        derived = by.get("derived") or {}
        bench = by.get("bench") or {}

        cells = {}
        prefill = {}
        ctx_lengths = []
        conc_levels = []
        bench_ts = None
        bench_data, json_path = best_json(bdir)
        if bench_data:
            meta = bench_data.get("metadata") or {}
            bench_ts = meta.get("timestamp") or os.path.basename(json_path or "")
            ctx_lengths = list(meta.get("context_lengths") or [])
            conc_levels = list(meta.get("concurrency_levels") or [])
            for r in bench_data.get("results") or []:
                c = int(r.get("concurrency"))
                t = int(r.get("context_tokens"))
                cells[f"{t}:{c}"] = {
                    "tps": round(r.get("aggregate_tps", 0) or 0, 2),
                    "ttft": r.get("ttft_p50") or r.get("ttft_avg"),
                    "done": int(r.get("num_completed", 0) or 0),
                    "err": int(r.get("num_errors", 0) or 0),
                }
            pf = bench_data.get("prefill") or {}
            if isinstance(pf, dict):
                for k, v in pf.items():
                    if isinstance(v, dict):
                        prefill[str(k)] = {
                            "ttft": v.get("ttft_seconds"),
                            "pps": v.get("tok_per_sec"),
                        }

        with open(compose_path) as fh:
            compose = fh.read()
        md = derived.get("model", os.path.basename(bdir))
        builds.append({
            "name": os.path.basename(bdir),
            "status": by.get("status", "UNKNOWN"),
            "engine_cat": engine_cat(derived.get("engine")),
            "engine_ref": derived.get("engine"),
            "target_gpu": gpu_of(derived),
            "model": md,
            "model_key": model_key(md),
            "params": derived.get("params"),
            "active": derived.get("active_params"),
            "arch": arch_of(derived),
            "quant": derived.get("quant"),
            "mtp": bool(derived.get("mtp", False)),
            "dflash": bool(derived.get("dflash", False)),
            "notes": derived.get("notes"),
            "bench_notes": bench.get("notes"),
            "bench_ts": bench_ts,
            "ctx_lengths": ctx_lengths,
            "conc_levels": conc_levels,
            "cells": cells,
            "prefill": prefill,
            "compose": compose,
        })
    return builds


def embed_json(obj):
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", default=DEFAULT_OUT)
    args = ap.parse_args()

    builds = load_builds()
    data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "colors": ENGINE_COLOR,
        "engine_labels": ENGINE_LABEL,
        "gpu_colors": GPU_COLOR,
        "gpu_labels": GPU_LABEL,
        "builds": builds,
    }
    with open(TEMPLATE) as fh:
        html = fh.read()
    html = html.replace("__DATA__", embed_json(data))

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as fh:
        fh.write(html)

    with_data = sum(1 for b in builds if b["cells"])
    print(f"Wrote {args.output}: {len(builds)} builds, {with_data} with benchmark data")


if __name__ == "__main__":
    main()
