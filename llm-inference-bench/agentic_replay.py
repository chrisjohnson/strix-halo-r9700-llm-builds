#!/usr/bin/env python3
"""Agentic-turn replay: what a dsh session actually experiences.

The plan's §2 metric is end-to-end latency of a turn in a GROWING conversation,
decomposed into cache-hit fraction, increment prefill rate, and decode. This
measures exactly that, against a real server, using the server's own timings.

A turn is: append tool results / user text to the history, re-send the WHOLE
history (what every harness does), and read back prompt_n / cache_n.
The interesting number is cache_n / prompt_n -- what fraction of the turn was
served from the prompt cache rather than re-prefilled.

Run:  agentic_replay.py --port 8180 [--turns 12] [--compact]
"""
import argparse, json, time, sys, pathlib
import httpx

REPO = pathlib.Path.home() / "strix-halo-r9700-llm-builds"

def tool_schemas():
    def T(name, desc, props, req):
        return {"type":"function","function":{"name":name,"description":desc,
                "parameters":{"type":"object","properties":props,"required":req}}}
    return [T("read_file","Read a file's contents",{"path":{"type":"string"}},["path"]),
            T("run_command","Run a shell command",{"command":{"type":"string"}},["command"]),
            T("grep","Search file contents",{"pattern":{"type":"string"}},["pattern"]),
            T("edit_file","Edit a file",{"path":{"type":"string"},"old":{"type":"string"},"new":{"type":"string"}},["path","old","new"])]

def system_prompt():
    # A real system prompt of realistic size, from this repo's own AGENTS.md.
    p = REPO / "AGENTS.md"
    body = p.read_text() if p.exists() else "You are a coding agent."
    return ("You are a coding agent working in a repository.\n\n" + body)[:6000]

def chunks(n, size=12000):
    """Real file content, as an agent would read it in pieces."""
    text = (REPO / "llm-inference-bench" / "app" / "orchestrator.py").read_text()
    out, i = [], 0
    while len(out) < n:
        out.append(text[i:i+size] if i < len(text) else text[:size])
        i += size
        if i >= len(text): i = 0
    return out

def ask(client, port, messages, max_tokens=64, thinking_off=True):
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if thinking_off:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    t0 = time.monotonic()
    r = client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=3600)
    wall = time.monotonic() - t0
    r.raise_for_status()
    d = r.json()
    return d, wall

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--compact-at", type=int, default=8, help="turn at which to simulate a compaction")
    ap.add_argument("--label", default="")
    a = ap.parse_args()

    sysp = system_prompt()
    tools = tool_schemas()
    bodies = chunks(a.turns + 2)
    msgs = [{"role":"system","content":sysp}]
    rows = []
    print(f"=== agentic replay on :{a.port} {a.label} ===")
    print(f"{'turn':>4} {'prompt_tot':>10} {'cached':>8} {'hit%':>6} {'evaluated':>9} {'prefill_s':>10} {'wall_s':>7} {'new_tok/s':>10}")
    with httpx.Client() as c:
        for turn in range(1, a.turns+1):
            is_compaction = (turn == a.compact_at)
            if is_compaction:
                # What most harnesses do: a compaction is a NEW conversation whose
                # only content is the whole history, so nothing matches the cache.
                flat = "\n\n".join(f"[{m['role']}] {m['content']}" for m in msgs)
                msgs = [{"role":"system","content":sysp},
                        {"role":"user","content":"Summarise this session so work can continue.\n\n"+flat}]
            else:
                msgs.append({"role":"user","content":
                    f"Continue. Tool result {turn}:\n\n{bodies[turn]}" if turn>1 else
                    f"Start. Tool result 1:\n\n{bodies[1]}"})
            d, wall = ask(c, a.port, msgs)
            tm = d.get("timings") or {}
            u  = d.get("usage") or {}
            # llama.cpp's timings: prompt_n is the number of tokens EVALUATED
            # this request and cache_n the number REUSED, so the total prompt is
            # their sum. Getting this backwards reports cache hits above 100%.
            pn = tm.get("prompt_n") or 0
            cn = tm.get("cache_n") or 0
            pms= tm.get("prompt_ms") or 0
            ptk= tm.get("predicted_n") or u.get("completion_tokens") or 0
            total = pn + cn
            hit= (cn/total*100) if total else 0
            new= pn
            rate = (pn/(pms/1000)) if pms else 0
            rows.append(dict(turn=turn, compaction=is_compaction, prompt_tokens=total, cached_tokens=cn,
                             hit_pct=hit, new_tokens=new, prefill_s=pms/1000 if pms else None,
                             wall_s=wall, new_tok_per_sec=rate, predicted=ptk))
            tag = "  <-- COMPACTION (cold)" if is_compaction else ""
            print(f"{turn:>4} {total:>10} {cn:>8} {hit:>5.1f}% {new:>9} {(pms/1000 if pms else 0):>10.2f} "
                  f"{wall:>7.2f} {rate:>10.0f}{tag}")
            # feed the assistant turn back in, as a harness does
            msg = d["choices"][0]["message"]
            msgs.append({"role":"assistant","content":(msg.get("content") or "")[:200] or "ok"})

    hot = [r for r in rows if not r["compaction"] and r["turn"]>1]
    print()
    if hot:
        print(f"  steady-state turns (n={len(hot)}): mean cache hit {sum(r['hit_pct'] for r in hot)/len(hot):.1f}%, "
              f"mean wall {sum(r['wall_s'] for r in hot)/len(hot):.2f}s, "
              f"mean increment rate {sum(r['new_tok_per_sec'] for r in hot)/len(hot):.0f} tok/s")
    comp = [r for r in rows if r["compaction"]]
    if comp:
        c0=comp[0]
        print(f"  compaction (cold re-read of the whole session): {c0['prompt_tokens']} tokens, "
              f"{c0['prefill_s']:.1f}s prefill, {c0['wall_s']:.1f}s wall")
    out = pathlib.Path(f"/home/dsh/scratch/tuning/agentic_{a.port}.json")
    out.write_text(json.dumps({"port":a.port,"label":a.label,"rows":rows}, indent=2))
    print(f"  wrote {out}")

main()
