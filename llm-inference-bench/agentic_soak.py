#!/usr/bin/env python3
"""Simulate a mild multi-turn agentic soak against any OpenAI-compatible
server: repeated screenshots plus periodic compaction (grow the conversation
over several turns, then replace the full history with a short synthetic
summary + the last couple of turns - the same shape real Claude Code/DSH
context compaction takes), run over several cycles.

Why this exists, and why it's different from vision_oom_repro.py or the
orchestrator's own throughput benchmark: both of those are single-shot - one
deep context, one image, one big batch, or one pass through a depth matrix.
Neither catches a *ratchet* - a resource that returns to roughly the same
footprint after each compaction in a healthy engine, but creeps upward cycle
over cycle in an unhealthy one (the real pattern behind M-160's actual
production incident: the climb took hours of ordinary use, not one extreme
request).

This script does NOT check host memory itself - run it alongside external
monitoring (Prometheus amdgpu_gtt_used_bytes / node_memory_MemAvailable_bytes,
or plain `free -h` on the box) and compare the readings BETWEEN cycles, same
discipline as every other repro this session. A healthy engine's readings
should look similar at the same point in every cycle; an unhealthy one's will
drift.

Usage:
  agentic_soak.py --port 8208 [--cycles 4] [--turns-per-cycle 8]
                   [--growth-per-turn 4000] [--image-every 3] [--max-tokens 60]

DO NOT run this against a model serving real traffic - same discipline as
every other probe in this directory. Check with Chris first.
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


def make_minimal_png(width: int = 4, height: int = 4, seed: int = 0) -> bytes:
    """Hand-built single-color RGB PNG - no PIL dependency. Color varies with
    seed so repeated screenshots in one session aren't byte-identical, same
    as real screenshots never are."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    rng = random.Random(seed)
    color = bytes([rng.randint(0, 255) for _ in range(3)])
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(height):
        raw += b"\x00" + color * width
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def synthetic_corpus(n_chars: int, seed: int) -> str:
    """Deterministic, non-repeating filler text standing in for a real coding
    turn's worth of tokens (a diff, a file read, a tool result)."""
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
        sentence = f"Step {i}: " + " ".join(
            rng.choice(words) for _ in range(rng.randint(8, 16))) + ". "
        out.append(sentence)
        length += len(sentence)
        i += 1
    return "".join(out)[:n_chars]


def post(port: int, messages: list, max_tokens: int, timeout: int = 600):
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


def reply_text(resp: dict) -> str:
    try:
        return resp.get("choices", [{}])[0].get("message", {}).get("content", "") or "ok"
    except Exception:  # noqa: BLE001
        return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--cycles", type=int, default=4)
    ap.add_argument("--turns-per-cycle", type=int, default=8)
    ap.add_argument("--growth-per-turn", type=int, default=4000,
                     help="chars of synthetic text per ordinary turn")
    ap.add_argument("--image-every", type=int, default=3,
                     help="insert a screenshot every N turns within a cycle")
    ap.add_argument("--max-tokens", type=int, default=60)
    ap.add_argument("--keep-tail", type=int, default=4,
                     help="messages kept verbatim across a compaction")
    args = ap.parse_args()

    messages = []
    img_seed = 0

    for cycle in range(args.cycles):
        print(f"\n=== cycle {cycle + 1}/{args.cycles} - starting at "
              f"{len(messages)} messages ===")
        for turn in range(args.turns_per_cycle):
            if turn > 0 and turn % args.image_every == 0:
                img_seed += 1
                png_b64 = base64.b64encode(
                    make_minimal_png(seed=img_seed)).decode()
                data_url = f"data:image/png;base64,{png_b64}"
                messages.append({"role": "user", "content": [
                    {"type": "text",
                     "text": f"Screenshot from cycle {cycle + 1}, turn {turn}:"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]})
                label = "image turn"
            else:
                text = synthetic_corpus(
                    args.growth_per_turn, seed=cycle * 1000 + turn)
                messages.append({"role": "user", "content": text})
                label = "text turn"

            ok, resp, dt = post(args.port, messages, args.max_tokens)
            if not ok:
                print(f"  cycle {cycle + 1} turn {turn} ({label}) FAILED "
                      f"after {dt:.1f}s: {resp}")
                sys.exit(1)
            t = resp.get("timings", {}) if isinstance(resp, dict) else {}
            reply = reply_text(resp)
            messages.append({"role": "assistant", "content": reply})
            print(f"  cycle {cycle + 1} turn {turn:>2} ({label:<9}) "
                  f"messages={len(messages):>3}  prompt_n={t.get('prompt_n', 0):>7,}  "
                  f"cache_n={t.get('cache_n', 0):>7,}  took={dt:>6.1f}s")

        # Compaction: replace the full history with a short synthetic summary
        # plus the last few messages verbatim - the same shape a real
        # compaction takes (summarize what happened, keep the recent tail,
        # keep going). This is the step that should let memory drop back to
        # roughly where it was at the start of the cycle, in a healthy engine.
        summary = (f"[Compacted summary of cycle {cycle + 1}: "
                   f"{args.turns_per_cycle} turns completed, "
                   f"{img_seed} screenshot(s) reviewed, work in progress.]")
        tail = messages[-args.keep_tail:] if args.keep_tail > 0 else []
        messages = [{"role": "user", "content": summary}] + tail
        print(f"  compacted: {len(messages)} messages remain for next cycle")

    print(f"\n*** SOAK COMPLETE: {args.cycles} cycles, "
          f"{args.cycles * args.turns_per_cycle} total turns, "
          f"{img_seed} screenshots, no request failures. ***")
    print("Check memory readings recorded between cycles for drift - this "
          "script does not check host memory itself.")


if __name__ == "__main__":
    main()
