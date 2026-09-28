#!/usr/bin/env python3
"""Probe how a llama.cpp-family server handles reasoning vs the answer budget.

Exists because this repo found - by running exactly this - that with thinking on
(these models' default) the thinking block consumes the ENTIRE max_tokens budget
at any size and `content` comes back EMPTY with finish_reason=length, the answer
stranded in `reasoning_content`. An agent harness reads that as a failed turn and
retries, so it presents as slowness rather than as an error. See
knowledge/research/2026-09-27-halogen-agentic-tuning-lessons.md.

Run against any build to check it, and to check whether a thinking bound fixes it:

  reasoning_probe.py --port 8180
  reasoning_probe.py --port 8180 --caps 2048,8192 --expect-answer-above 4096

A `--reasoning-budget N` only acts when the caller's cap is LARGER than N; below
that the cap ends generation first and the answer is still empty. That asymmetry
is the point of the caps sweep, not an artefact of it.
"""
import argparse, sys
import httpx

PROMPT = ("Solve this carefully, showing your full reasoning: a bat and a ball cost "
          "$1.10 together. The bat costs $1.00 more than the ball. How much is the ball? "
          "Then prove it algebraically, then verify by substitution, then consider two "
          "alternative interpretations of the wording and rule them out.")

def ask(port, max_tokens, extra=None, timeout=3600):
    body = {"messages":[{"role":"user","content":PROMPT}], "max_tokens":max_tokens, "temperature":0}
    if extra: body.update(extra)
    r = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=timeout)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    d = r.json(); ch = d["choices"][0]; m = ch["message"]
    return dict(finish=ch.get("finish_reason"),
                content_len=len(m.get("content") or ""),
                reasoning_len=len(m.get("reasoning_content") or ""),
                completion=(d.get("usage") or {}).get("completion_tokens"),
                keys=sorted(m.keys())), None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--caps", default="32,64,2048,8192")
    ap.add_argument("--expect-answer-above", type=int, default=None,
                    help="exit non-zero if a cap above this yields empty content")
    a = ap.parse_args()
    caps = [int(c) for c in a.caps.split(",")]
    print(f"=== reasoning probe on :{a.port} ===")
    print(f"  {'cap':>7} {'finish':>8} {'content':>8} {'reasoning':>10} {'completion':>11}  verdict")
    bad = 0
    for cap in caps:
        res, err = ask(a.port, cap)
        if err:
            print(f"  {cap:>7} {err}"); continue
        empty = res["content_len"] == 0
        verdict = "EMPTY CONTENT (harness sees a failed turn)" if empty else "answer present"
        if empty: bad += 1
        print(f"  {cap:>7} {str(res['finish']):>8} {res['content_len']:>8} {res['reasoning_len']:>10} "
              f"{str(res['completion']):>11}  {verdict}")
    print()
    for label, extra in (("reasoning_effort=none", {"reasoning_effort":"none"}),
                         ("enable_thinking=false", {"chat_template_kwargs":{"enable_thinking":False}})):
        res, err = ask(a.port, caps[0], extra)
        if not err:
            print(f"  control + {label:<22} content_len={res['content_len']} reasoning_len={res['reasoning_len']}")
    if a.expect_answer_above is not None:
        for cap in caps:
            if cap > a.expect_answer_above:
                res, err = ask(a.port, cap)
                if not err and res["content_len"] == 0:
                    print(f"\nFAIL: cap {cap} > {a.expect_answer_above} still returned empty content")
                    sys.exit(1)
        print(f"\nOK: every cap above {a.expect_answer_above} returned an answer")

main()
