#!/usr/bin/env python3
"""Reproduce the qwen4exp vision+long-context OOM crash (M-158/M-159,
ggml-org/llama.cpp#30032) against any OpenAI-compatible llama.cpp-family
server, to check whether a given engine build still has it.

Root cause (see knowledge/research/2026-10-05-qwen4exp-mtp-vision-oom.md):
once any 2D-positioned (image) cell enters the KV cache, this model's QSA
sparse-attention indexer permanently falls back from a cheap block-granularity
selection path to one that materializes an O(n_kv x ubatch_size) tensor per
sparse layer. The crash shows up when a request processes a large batch of
NEW tokens (ubatch-sized) once the context is already deep AND an image has
been seen earlier in the same conversation.

This script is self-contained on purpose - no external corpus file, no PIL -
so it is exactly reproducible from a bare checkout, not dependent on
whatever happens to be lying around on a given box.

Steps:
  1. Build a deep context (default ~150k tokens) from synthetic, non-repeating
     text via incremental cache_prompt growth (cheap: each step only pays for
     the newly-added tokens, same mechanism incremental_prefill.py uses).
  2. Add a message containing a minimal valid PNG (hand-built, no PIL) -
     plants a 2D-positioned cell in the cache at depth.
  3. Add one more big chunk of new text (default 8192 tokens, matching the
     -ub8192 batch size the original crashes were measured at) - this is the
     step that crashed on the original engine.

Usage:
  vision_oom_repro.py --port 8199 [--target-depth 150000] [--final-chunk 8192]

DO NOT run this against a model serving real traffic - same discipline as
every other probe in this directory (see qsa_compression_probe.py's own
warning). Check with Chris first; this is a deliberate crash test.
"""
import argparse
import base64
import json
import random
import struct
import sys
import time
import urllib.request
import zlib


def make_minimal_png(width: int = 4, height: int = 4) -> bytes:
    """Hand-built single-color RGB PNG - no PIL dependency."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + bytes([200, 60, 60]) * width  # filter byte + RGB row
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def synthetic_corpus(n_chars: int, seed: int = 20261005) -> str:
    """Deterministic, non-repeating filler text - avoids any cache-hit
    shortcut a repeating pattern could trigger, without needing a real file."""
    rng = random.Random(seed)
    words = [
        "halo", "strix", "vector", "quartz", "lemon", "orbit", "kettle",
        "ferry", "granite", "willow", "cobalt", "ember", "marble", "thistle",
        "falcon", "harbor", "indigo", "juniper", "kestrel", "lantern",
        "meadow", "nautical", "opal", "pewter", "quarry", "ridge", "saffron",
        "tundra", "umber", "velvet", "walnut", "xenon", "yarrow", "zephyr",
    ]
    out = []
    length = 0
    i = 0
    while length < n_chars:
        sentence = f"Entry {i}: " + " ".join(
            rng.choice(words) for _ in range(rng.randint(8, 16))) + ". "
        out.append(sentence)
        length += len(sentence)
        i += 1
    return "".join(out)[:n_chars]


def post(port: int, messages: list, max_tokens: int = 1, timeout: int = 3000):
    body = {"model": "m", "messages": messages, "max_tokens": max_tokens,
            "stream": False, "cache_prompt": True}
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return True, d, time.time() - t0
    except urllib.error.HTTPError as e:
        return False, e.read().decode(errors="replace"), time.time() - t0
    except Exception as e:  # noqa: BLE001 - want to see exactly what broke
        return False, str(e), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--target-depth", type=int, default=150000,
                     help="tokens of plain text before the image (~3.3 chars/tok)")
    ap.add_argument("--final-chunk", type=int, default=8192,
                     help="new tokens added in the step that should crash")
    ap.add_argument("--step-chars", type=int, default=400000,
                     help="chars per incremental growth step (keeps each ask() cheap)")
    args = ap.parse_args()

    chars_per_tok = 3.3
    target_chars = int(args.target_depth * chars_per_tok)
    final_chars = int(args.final_chunk * chars_per_tok)

    print(f"[1/3] Building depth to ~{args.target_depth:,} tokens "
          f"({target_chars:,} chars) via incremental cache_prompt growth...")
    text = ""
    grown = 0
    while grown < target_chars:
        step = min(args.step_chars, target_chars - grown)
        text += synthetic_corpus(step, seed=20261005 + grown)
        grown += step
        ok, resp, dt = post(args.port, [{"role": "user", "content": text}])
        if not ok:
            print(f"  FAILED while building depth at ~{len(text)//3} tok "
                  f"after {dt:.1f}s: {resp}")
            sys.exit(1)
        t = resp.get("timings", {}) if isinstance(resp, dict) else {}
        print(f"  depth~{len(text)//3:>8,} tok  prompt_n={t.get('prompt_n',0):>7,}  "
              f"cache_n={t.get('cache_n',0):>7,}  took={dt:>7.1f}s")

    print(f"[2/3] Planting an image at depth ~{len(text)//3:,} tokens...")
    png_b64 = base64.b64encode(make_minimal_png()).decode()
    data_url = f"data:image/png;base64,{png_b64}"
    messages = [
        {"role": "user", "content": text},
        {"role": "user", "content": [
            {"type": "text", "text": "Describe this image in one word."},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ]
    ok, resp, dt = post(args.port, messages, max_tokens=16)
    if not ok:
        print(f"  FAILED planting image after {dt:.1f}s: {resp}")
        sys.exit(1)
    t = resp.get("timings", {}) if isinstance(resp, dict) else {}
    print(f"  image planted  prompt_n={t.get('prompt_n',0):>7,}  "
          f"cache_n={t.get('cache_n',0):>7,}  took={dt:>7.1f}s")
    reply = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    print(f"  model replied: {reply!r}")

    print(f"[3/3] Adding {args.final_chunk:,} new tokens after the image - "
          f"this is the step that crashed the original engine (M-158/M-159)...")
    final_text = synthetic_corpus(final_chars, seed=99)
    messages.append({"role": "assistant", "content": reply or "ok"})
    messages.append({"role": "user", "content": final_text})
    ok, resp, dt = post(args.port, messages, max_tokens=8, timeout=3600)
    if not ok:
        print(f"\n*** CRASH REPRODUCED after {dt:.1f}s: {resp}\n")
        sys.exit(2)
    t = resp.get("timings", {}) if isinstance(resp, dict) else {}
    print(f"  SURVIVED  prompt_n={t.get('prompt_n',0):>7,}  "
          f"cache_n={t.get('cache_n',0):>7,}  took={dt:>7.1f}s")
    print("\n*** NO CRASH - this build handled vision + depth + a large "
          "new batch without the known OOM. ***")


if __name__ == "__main__":
    main()
