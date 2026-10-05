#!/usr/bin/env python3
"""Probe Qwen3.8-Flash-Next for compression-induced hallucination in its QSA
sparse-attention layers, under real long-context load.

Why this exists: a third-party report (video "Qwen3.8-Flash-Next Hallucinates.
I Fixed It With One Sparse Attention Setting", cross-referenced against GitHub
issue pegainfer-project/pegainfer#1105) found this model hallucinating on a
long-context CTF benchmark, traced to its QSA sparse-attention layers
compressing context. Their fix (SGLang's indexer-budget flag, 2048->4096) does
NOT apply here - this engine (pwilkin's llama.cpp fork) exposes no equivalent
flag (confirmed: `llama-server --help` has no indexer/qsa/sparse flag at all).
Our own GGUF's `qwen4exp.attention.compress_ratios` (48 values, checked via
scripts/gguf_meta.py) is a clean, regular [0,0,0,4]x12 pattern - NOT the
all-zeros corruption the report's OTHER finding described for a different
GGUF - so the known bug's specific root cause doesn't look present either.
Neither of those checks is a substitute for actually testing the failure mode
on OUR build, which this script does.

Design: plant N independently-verifiable "needle" facts at spread-out
positions within a long, non-repeating distractor document, then ask one
pointed question per needle and grade the answer against the known-correct
value (never taken on trust - this script generates the needles, so ground
truth is exact, not model-reported). Needle spacing is varied (tight vs wide)
within the same run, since the hallucination mechanism under test is
compression merging/blurring nearby positions, not just raw depth - a plain
single-needle test at increasing depth (the usual NIAH pattern) would not
distinguish a depth effect from a density effect.

DO NOT run this against a model currently serving real traffic - it needs the
server to itself for the duration (see this repo's own benchmark discipline:
never run concurrent work during a benchmark pass). Check with Chris first.

Usage:
  qsa_compression_probe.py --port 8195 --depths 16384,65536,131072,245760
  qsa_compression_probe.py --port 8195 --depths 131072 --spacing tight,wide
"""
import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.request

# Deliberately boring, non-repeating distractor content - varying sentence
# structure so the server can't shortcut via literal repetition, but nothing
# worth attending to on its own (keeps attention on the needles meaningful).
TOPICS = ["deployment", "memory", "context", "cache", "inference", "latency",
          "throughput", "kernel", "buffer", "network", "pipeline", "session",
          "token", "weight", "tensor", "graph", "schedule", "allocation",
          "runtime", "driver", "firmware", "registry", "endpoint", "queue"]
VERBS = ["increases", "decreases", "stabilizes", "fluctuates", "depends on",
          "correlates with", "overrides", "extends", "truncates", "replaces",
          "duplicates", "mirrors", "diverges from", "converges to", "bypasses"]

NEEDLE_TEMPLATES = [
    ("access code", lambda r: f"{r.randrange(100000, 999999)}",
     "The maintenance access code for this subsystem is {val}."),
    ("port number", lambda r: f"{r.randrange(20000, 65000)}",
     "The internal diagnostic port for this subsystem is {val}."),
    ("checksum", lambda r: "".join(r.choice("0123456789abcdef") for _ in range(8)),
     "The expected checksum for this subsystem's config is {val}."),
    ("serial suffix", lambda r: f"{r.choice('ABCDEFGH')}{r.randrange(1000, 9999)}",
     "The serial suffix assigned to this subsystem is {val}."),
]


def distractor_sentence(r):
    a, b, c = r.choice(TOPICS), r.choice(VERBS), r.choice(TOPICS)
    return f"the {a} subsystem {b} the {c} allocation under sustained load conditions observed during the trial run."


def build_haystack(target_tokens, n_needles, spacing, seed):
    """spacing: 'tight' clusters needles close together; 'wide' spreads them
    evenly across the whole document. Returns (text, [(question, answer), ...])."""
    r = random.Random(seed)
    approx_chars = target_tokens * 4
    sentence_chars = 90  # rough average
    total_sentences = max(approx_chars // sentence_chars, n_needles * 2)

    if spacing == "tight":
        # all needles inside one ~5% window, elsewhere empty of needles
        window_start = total_sentences // 2
        positions = sorted(r.sample(range(window_start, window_start + max(total_sentences // 20, n_needles)), n_needles))
    else:
        # evenly spread across the full document
        step = total_sentences // (n_needles + 1)
        positions = [step * (i + 1) + r.randrange(-step // 4, step // 4 + 1) for i in range(n_needles)]
        positions = sorted(max(0, min(p, total_sentences - 1)) for p in positions)

    qa = []
    lines = []
    pos_set = {}
    for i, pos in enumerate(positions):
        label, gen, template = NEEDLE_TEMPLATES[i % len(NEEDLE_TEMPLATES)]
        val = gen(r)
        subsystem = f"{r.choice(TOPICS)}-{r.randrange(100,999)}"
        pos_set[pos] = template.format(val=val).replace("this subsystem", f"subsystem {subsystem}")
        qa.append((f"What is the {label} for subsystem {subsystem}?", val))

    for i in range(total_sentences):
        if i in pos_set:
            lines.append(pos_set[i])
        else:
            lines.append(distractor_sentence(r))
    return " ".join(lines), qa


def ask(port, prompt, timeout=1800):
    body = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 128, "temperature": 0}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.load(resp)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:200]}"
    except urllib.error.URLError as e:
        return None, f"URLError: {e}"
    return d["choices"][0]["message"].get("content", ""), None


def grade(answer, expected):
    if answer is None:
        return False
    return expected.lower() in re.sub(r"[\s*_`]", "", answer.lower())


def run_one(port, target_tokens, n_needles, spacing, seed):
    haystack, qa = build_haystack(target_tokens, n_needles, spacing, seed)
    results = []
    # Single shared context: ask all questions in one follow-up turn after the
    # haystack, via one combined prompt per question (independent requests,
    # same haystack+seed, so cache_prompt reuse keeps this affordable).
    for q, expected in qa:
        prompt = f"{haystack}\n\n{q} Answer with only the value, nothing else."
        answer, err = ask(port, prompt)
        results.append(dict(question=q, expected=expected, answer=answer, error=err,
                             correct=grade(answer, expected) if err is None else False))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--depths", default="16384,65536,131072,245760")
    ap.add_argument("--spacing", default="tight,wide")
    ap.add_argument("--needles", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261004)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    depths = [int(d) for d in a.depths.split(",")]
    spacings = a.spacing.split(",")

    all_rows = []
    print(f"=== QSA compression-hallucination probe on :{a.port} ===")
    for depth in depths:
        for spacing in spacings:
            rows = run_one(a.port, depth, a.needles, spacing, a.seed)
            n_ok = sum(r["correct"] for r in rows)
            print(f"  depth={depth:>7} spacing={spacing:<5}  {n_ok}/{len(rows)} correct")
            for r in rows:
                if not r["correct"]:
                    print(f"      MISS: {r['question']} -> expected {r['expected']!r}, got {str(r['answer'])[:80]!r} ({r['error'] or ''})")
                all_rows.append(dict(depth=depth, spacing=spacing, **r))

    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(all_rows, f, indent=2)
        print(f"wrote {a.json_out}")

    total = len(all_rows)
    ok = sum(r["correct"] for r in all_rows)
    print(f"\nTOTAL: {ok}/{total} correct")
    tight = [r for r in all_rows if r["spacing"] == "tight"]
    wide = [r for r in all_rows if r["spacing"] == "wide"]
    if tight and wide:
        print(f"  tight-spacing: {sum(r['correct'] for r in tight)}/{len(tight)}")
        print(f"  wide-spacing:  {sum(r['correct'] for r in wide)}/{len(wide)}")
    sys.exit(0 if ok == total else 1)


if __name__ == "__main__":
    main()
