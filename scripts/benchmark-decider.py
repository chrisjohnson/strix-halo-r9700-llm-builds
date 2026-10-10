#!/usr/bin/env python3
"""Benchmark for decision models (/v1/systemone), e.g. openjev-27b-q4km.

The existing llm-inference-bench orchestrator assumes /v1/chat/completions
(prompt -> generated tokens) and doesn't fit this model type: a single
forward pass over typed questions, zero output tokens, no autoregressive
decode to measure. This script is a standalone replacement, not a client of
that orchestrator (and deliberately so - the orchestrator stops every other
build sharing the target GPU before running, which would take down the
standing qwen3.8-flash-next-hgnv2 build this one is meant to coexist with).

Measures:
  - Correctness: unambiguous-by-construction triage/routing/scoring prompts
    where the "right" answer is obvious to a human reader, checked against
    the model's top choice.
  - Latency: wall-clock per request (single forward pass, no streaming).
  - usage.output_tokens: expected to be 0 on every request - confirms the
    "no autoregressive generation" architecture claim directly rather than
    assuming it.

Usage: benchmark-decider.py [base_url]  (default http://127.0.0.1:8212)
"""
import json
import sys
import time
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8212"

CASES = [
    {
        "name": "billing_vs_shipping",
        "state": "Customer message: I was charged twice for order #4471 and "
                 "nobody has refunded me yet.",
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "payment, charge, or refund issue",
                    "shipping": "package tracking or delivery issue",
                    "technical": "app or website bug",
                },
            }
        },
        "expect": {"route": "billing"},
    },
    {
        "name": "shipping_not_billing",
        "state": "Customer message: my package says delivered but I never "
                 "got it, where is it?",
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "payment, charge, or refund issue",
                    "shipping": "package tracking or delivery issue",
                    "technical": "app or website bug",
                },
            }
        },
        "expect": {"route": "shipping"},
    },
    {
        "name": "urgent_binary_clear_yes",
        "state": "Customer message: URGENT - my card was just charged $4000 "
                 "fraudulently, I need this frozen right now.",
        "questions": {
            "urgent": {
                "type": "noul",
                "instructions": "Does this need a human to intervene within "
                                 "the hour?",
            }
        },
        "expect_noul_high": "urgent",
    },
    {
        "name": "urgent_binary_clear_no",
        "state": "Customer message: just wanted to say the new app update "
                 "looks nice, no issues.",
        "questions": {
            "urgent": {
                "type": "noul",
                "instructions": "Does this need a human to intervene within "
                                 "the hour?",
            }
        },
        "expect_noul_low": "urgent",
    },
    {
        "name": "frustration_score_angry",
        "state": "Customer message: this is the THIRD time I've contacted "
                 "support about the same issue and nothing has been fixed. "
                 "I am extremely unhappy and considering cancelling.",
        "questions": {
            "frustration": {
                "type": "score",
                "instructions": "How frustrated is the customer?",
                "criteria": ["calm", "mildly annoyed", "annoyed", "angry"],
            }
        },
        "expect_score_in": ["angry", "annoyed"],
    },
    {
        "name": "frustration_score_calm",
        "state": "Customer message: hey, quick question - what's the "
                 "warranty period on the charger I bought last month?",
        "questions": {
            "frustration": {
                "type": "score",
                "instructions": "How frustrated is the customer?",
                "criteria": ["calm", "mildly annoyed", "annoyed", "angry"],
            }
        },
        "expect_score_in": ["calm", "mildly annoyed"],
    },
]


def post(path, payload):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
    return body, time.monotonic() - t0


def check(case, answers):
    if "expect" in case:
        for q, want in case["expect"].items():
            got = answers.get(q, {}).get("choice")
            if got != want:
                return False, f"{q}: expected {want!r}, got {got!r}"
    if "expect_noul_high" in case:
        q = case["expect_noul_high"]
        v = answers.get(q, {}).get("noul", -1)
        if v < 0.5:
            return False, f"{q}: expected noul>=0.5, got {v}"
    if "expect_noul_low" in case:
        q = case["expect_noul_low"]
        v = answers.get(q, {}).get("noul", 2)
        if v > 0.5:
            return False, f"{q}: expected noul<=0.5, got {v}"
    if "expect_score_in" in case:
        for q, allowed in [(k, v) for k, v in case.items() if k == "expect_score_in"]:
            pass
    return True, ""


def main():
    results = []
    latencies = []
    output_token_violations = []
    passed = 0
    for case in CASES:
        payload = {"state": case["state"], "questions": case["questions"]}
        try:
            body, dt = post("/v1/systemone", payload)
        except Exception as e:
            print(f"[FAIL] {case['name']}: request error: {e}")
            results.append((case["name"], False, str(e)))
            continue
        latencies.append(dt)
        out_tok = body.get("usage", {}).get("output_tokens")
        if out_tok != 0:
            output_token_violations.append((case["name"], out_tok))

        answers = body.get("answers", {})
        ok = True
        detail = ""
        if "expect" in case:
            ok, detail = check(case, answers)
        elif "expect_noul_high" in case or "expect_noul_low" in case:
            ok, detail = check(case, answers)
        elif "expect_score_in" in case:
            q = list(case["questions"].keys())[0]
            got = answers.get(q, {}).get("score") or answers.get(q, {}).get("choice")
            ok = got in case["expect_score_in"]
            detail = f"{q}: got {got!r}, allowed {case['expect_score_in']}"

        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"[{status}] {case['name']} ({dt*1000:.0f}ms){'' if ok else ' - ' + detail}")
        results.append((case["name"], ok, detail))

    n = len(CASES)
    print(f"\n{passed}/{n} correctness checks passed")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        print(f"Latency: min={min(latencies)*1000:.0f}ms p50={p50*1000:.0f}ms "
              f"max={max(latencies)*1000:.0f}ms (n={len(latencies)})")
    if output_token_violations:
        print(f"WARNING: output_tokens != 0 for: {output_token_violations}")
    else:
        print("Confirmed: output_tokens == 0 on every request (single forward "
              "pass, no autoregressive generation, no growing KV cache).")


if __name__ == "__main__":
    main()
