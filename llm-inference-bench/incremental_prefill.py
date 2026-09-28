#!/usr/bin/env python3
"""Measure the *incremental* prefill cost of a growing context with the prompt
cache working - i.e. what an agentic loop actually pays per turn, as opposed to
the cold full re-prefill the benchmark ladder measures."""
import json, sys, urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8152
DOC_TOKENS = int(sys.argv[2]) if len(sys.argv) > 2 else 64000
EXTRA_TOKENS = 2000

corpus = open("/home/dsh/scratch/tuning/corpus.txt", errors="replace").read()
# ~3.3 chars/token for this source-heavy corpus; aim for DOC_TOKENS
doc = corpus[: int(DOC_TOKENS * 3.3)]
extra = corpus[100000: 100000 + int(EXTRA_TOKENS * 3.3)]

def ask(text, label):
    body = {"model": "m", "messages": [{"role": "user", "content": text}],
            "max_tokens": 1, "stream": False, "cache_prompt": True}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2400) as r:
        d = json.load(r)
    t = d.get("timings") or {}
    print(f"{label:<34} prompt_n={t.get('prompt_n',0):>7,}  cache_n={t.get('cache_n',0):>7,}  "
          f"took={t.get('prompt_ms',0)/1000:>8.2f}s  rate={t.get('prompt_per_second',0):>7.1f} tok/s")
    return t

print(f"flash-next on :{PORT} - incremental prefill with the prompt cache warm")
t1 = ask(doc, "1. first request (cold)")
t3 = ask(doc + extra, f"2. context grown by ~{EXTRA_TOKENS} tok")
t4 = ask(doc + extra, "3. identical repeat")
print()
tot = (t1.get("prompt_n",0) + t1.get("cache_n",0))
print(f"first request processed {t1.get('prompt_n',0):,} of {tot:,} tokens "
      f"({t1.get('prompt_ms',0)/1000:.1f}s)")
print(f"grown request processed only {t3.get('prompt_n',0):,} tokens "
      f"({t3.get('prompt_ms',0)/1000:.2f}s) - the rest came from cache")
