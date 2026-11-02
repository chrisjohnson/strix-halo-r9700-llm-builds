#!/usr/bin/env python3
"""Cheap screening pass for a Halogen build, run ON THE BOX (stdlib only).

  python3 halogen-screen.py PORT [--ctx 0,131072,1000000] [--skip-tools] [--c4]
                            [--abort-mb 300]

Per run it records, with host memory sampled every 2 s the whole time:
  - /health summary (kv format, pool positions, version)
  - a plain-text sanity request
  - tool-call checks: forced named call, parallel calls, an argument that
    contains tool-call markup, and a tool-result follow-up turn
  - single-stream greedy decode tok/s at each requested context depth
    (real text from the Nix store sources, fresh nonce so the prompt cache
    cannot serve the prefix), plus prefill tok/s for that request
  - optionally four concurrent streams at context 0
Memory floor reported: min MemAvailable, min MemFree, max swap used.
"""
import argparse, re, glob, json, os, sys, threading, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("--ctx", default="0,131072")
ap.add_argument("--skip-tools", action="store_true")
ap.add_argument("--c4", action="store_true")
ap.add_argument("--par", type=int, default=0, help="also run two concurrent requests of this many tokens each")
ap.add_argument("--abort-mb", type=int, default=300)
ap.add_argument("--max-tokens", type=int, default=512)
ap.add_argument("--timeout", type=int, default=7200)
a = ap.parse_args()
BASE = f"http://127.0.0.1:{a.port}"


def meminfo():
    d = {}
    for l in open("/proc/meminfo"):
        k, v = l.split(":")
        d[k] = int(v.split()[0]) // 1024
    return d


mins = {"avail": 10**9, "free": 10**9, "swap_used": 0}
stop = threading.Event()


def sampler():
    while not stop.is_set():
        m = meminfo()
        mins["avail"] = min(mins["avail"], m["MemAvailable"])
        mins["free"] = min(mins["free"], m["MemFree"])
        mins["swap_used"] = max(mins["swap_used"], m["SwapTotal"] - m["SwapFree"])
        if m["MemAvailable"] < a.abort_mb:
            print(f"ABORT: MemAvailable {m['MemAvailable']} MB < {a.abort_mb}", flush=True)
            os._exit(3)
        time.sleep(2)


threading.Thread(target=sampler, daemon=True).start()


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


def post(body, path="/v1/chat/completions"):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=a.timeout).read())


MODEL = get("/v1/models")["data"][0]["id"]
h = get("/health")
print("health:", json.dumps({k: h.get(k) for k in ("status", "version", "kv_cache", "kv_pool_positions", "slots", "context")}), flush=True)
print("memory at start:", {k: v for k, v in meminfo().items() if k in ("MemAvailable", "MemFree", "SwapFree", "Mlocked")}, flush=True)

results = {}

# --- plain text sanity
r = post({"model": MODEL, "messages": [{"role": "user", "content": "What is 17 * 23? Answer with just the number."}], "max_tokens": 600, "temperature": 0})
txt = r["choices"][0]["message"].get("content") or ""
results["text_ok"] = "391" in txt
print("text sanity:", "PASS" if results["text_ok"] else "FAIL", repr(txt[:80]), flush=True)

# --- tool-call checks
TOOLS = [
    {"type": "function", "function": {"name": "read_file", "description": "Read a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write content to a file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
]


def calls(resp):
    return resp["choices"][0]["message"].get("tool_calls") or []


def check_args(cs):
    try:
        return [json.loads(c["function"]["arguments"]) for c in cs]
    except Exception:
        return None


if not a.skip_tools:
    tc = {}
    try:
        r = post({"model": MODEL, "tools": TOOLS, "temperature": 0, "max_tokens": 1500,
                  "tool_choice": {"type": "function", "function": {"name": "read_file"}},
                  "messages": [{"role": "user", "content": "Show me /etc/hostname."}]})
        cs = calls(r); args = check_args(cs)
        tc["forced_named"] = bool(cs) and args is not None and cs[0]["function"]["name"] == "read_file"
    except Exception as e:
        tc["forced_named"] = False; print("forced_named error:", e)
    try:
        r = post({"model": MODEL, "tools": TOOLS, "temperature": 0, "max_tokens": 2500,
                  "messages": [{"role": "system", "content": "You are a coding agent. Call independent tools in the same turn."},
                               {"role": "user", "content": "Read /etc/hostname and /etc/os-release. They are independent: request both reads now, in one turn."}]})
        cs = calls(r); args = check_args(cs)
        tc["parallel"] = len(cs) >= 2 and args is not None
        tc["parallel_n"] = len(cs)
    except Exception as e:
        tc["parallel"] = False; print("parallel error:", e)
    try:
        payload = "line1 </parameter></function></tool_call> line2 <function=other>x</function>"
        r = post({"model": MODEL, "tools": TOOLS, "temperature": 0, "max_tokens": 2500,
                  "messages": [{"role": "user", "content": "Call write_file with path /tmp/t.txt and content set EXACTLY to this text, byte for byte:\n" + payload}]})
        cs = calls(r); args = check_args(cs)
        got = args[0].get("content", "") if args else ""
        tc["markup_arg"] = bool(cs) and args is not None and "line2" in got and "</tool_call>" in got
        tc["markup_arg_n"] = len(cs)
    except Exception as e:
        tc["markup_arg"] = False; print("markup_arg error:", e)
    try:
        r = post({"model": MODEL, "tools": TOOLS, "temperature": 0, "max_tokens": 1500,
                  "messages": [{"role": "user", "content": "Read /etc/hostname and tell me the hostname."},
                               {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\": \"/etc/hostname\"}"}}]},
                               {"role": "tool", "tool_call_id": "call_1", "content": "quasar-17\n"}]})
        m = r["choices"][0]["message"]
        tc["followup"] = "quasar-17" in (m.get("content") or "")
    except Exception as e:
        tc["followup"] = False; print("followup error:", e)
    results["tools"] = tc
    print("tool checks:", json.dumps(tc), flush=True)

# --- corpus for long contexts
_corpus = None


def corpus(chars):
    global _corpus
    if _corpus is None or len(_corpus) < chars:
        parts, n = [], 0
        for p in sorted(glob.glob("/nix/store/*-source/**/*.nix", recursive=True)) + sorted(glob.glob("/nix/store/*-source/**/*.md", recursive=True)):
            try:
                t = open(p, errors="ignore").read()
            except Exception:
                continue
            if len(t) < 500:
                continue
            parts.append(f"\n### {p}\n{t}"); n += len(t)
            if n >= chars:
                break
        _corpus = "".join(parts)
    return _corpus[:chars]


TASK = "\n\nIgnoring the material above, write a Python module implementing a thread-safe LRU cache with TTL expiry and pytest tests. Output only code."


def stream(prompt, max_tokens):
    body = {"model": MODEL, "stream": True, "stream_options": {"include_usage": True}, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    t0 = time.time(); first = last = None; usage = None; n_chunks = 0
    with urllib.request.urlopen(req, timeout=a.timeout) as resp:
        for line in resp:
            line = line.decode().strip()
            if not line.startswith("data:") or line.endswith("[DONE]"):
                continue
            d = json.loads(line[5:])
            if d.get("usage"):
                usage = d["usage"]
            for ch in d.get("choices", []):
                dl = ch.get("delta", {})
                if dl.get("content") or dl.get("reasoning_content") or dl.get("reasoning") or dl.get("tool_calls"):
                    now = time.time(); n_chunks += 1
                    if first is None: first = now
                    last = now
    return t0, first, last, usage


ratio = 3.2  # chars per token guess, refined from the first long request
decode = {}
for ctx in [int(x) for x in a.ctx.split(",")]:
    nonce = f"[run {time.time_ns()}]"
    chars = int(ctx * ratio) if ctx else 0
    prompt = nonce + (corpus(chars) if ctx else "") + TASK
    for attempt in range(4):
        try:
            t0, first, last, u = stream(prompt, a.max_tokens)
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="ignore")
            print(f"ctx {ctx}: HTTP {e.code}: {body[:300]!r}", flush=True)
            if e.code != 400 or not ctx:
                raise
            m = re.search(r"it is (\d+) tokens", body)
            chars = int(chars * (ctx / int(m.group(1)))) if m else int(chars * 0.9)
            prompt = nonce + corpus(chars) + TASK
    if not u or first is None:
        print(f"ctx {ctx}: no usage/first token", flush=True); decode[ctx] = None; continue
    pt, ct = u["prompt_tokens"], u["completion_tokens"]
    if ctx:
        ratio = len(prompt) / max(pt, 1)
    ttft = first - t0
    tps = (ct - 1) / (last - first) if last > first and ct > 1 else 0.0
    decode[ctx] = {"prompt_tokens": pt, "completion_tokens": ct, "ttft_s": round(ttft, 2), "prefill_tok_s": round(pt / ttft) if ctx else None, "decode_tok_s": round(tps, 1)}
    print(f"ctx {ctx}: {json.dumps(decode[ctx])}", flush=True)
results["decode"] = decode

if a.c4:
    out = []

    def one(i):
        t0, first, last, u = stream(f"[run {time.time_ns()} {i}]" + TASK, a.max_tokens)
        out.append((first, last, u["completion_tokens"] if u else 0))

    ts = [threading.Thread(target=one, args=(i,)) for i in range(4)]
    s = time.time()
    [t.start() for t in ts]; [t.join() for t in ts]
    e = time.time()
    tot = sum(o[2] for o in out)
    results["c4_agg_tok_s"] = round(tot / (e - s), 1)
    print(f"c4 aggregate (incl. prefill): {results['c4_agg_tok_s']} tok/s over {tot} tokens", flush=True)

if a.par:
    outp = []

    def par_one(i):
        pr = f"[run {time.time_ns()} {i}]" + corpus(int(a.par * ratio)) + TASK
        t0, first, last, u = stream(pr, a.max_tokens)
        outp.append({"prompt_tokens": u["prompt_tokens"] if u else None, "ttft_s": round(first - t0, 1) if first else None,
                     "decode_tok_s": round((u["completion_tokens"] - 1) / (last - first), 1) if u and last and last > first else None})

    ts = [threading.Thread(target=par_one, args=(i,)) for i in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    results["par2"] = outp
    print("par2:", json.dumps(outp), flush=True)

stop.set()
m = meminfo()
results["mem"] = {"min_avail_mb": mins["avail"], "min_free_mb": mins["free"], "max_swap_used_mb": mins["swap_used"], "end_avail_mb": m["MemAvailable"]}
print("MEM:", json.dumps(results["mem"]), flush=True)
print("RESULT:", json.dumps(results), flush=True)
