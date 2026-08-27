---
id: 2026-07-26-ollama-chat-template-root-caused-fixed
date: 2026-07-26
source: "HANDOFF.md (\"Decisions made this session\", lines 338-365)"
tags: [ollama, chat-template, tool-calling, bug-fix]
status: active
---

# Ollama's broken-chat-template gap: root-caused and fixed for 3 of 4 registered models

**Decided/fixed**: root-caused via reading Ollama's own `v0.17.7` source (not guessed).
The GGUF files' embedded `tokenizer.chat_template` Jinja2 metadata is real and complete —
the bug is in `ollama create`'s auto-detection (`server/model.go`'s
`detectChatTemplate`), which only matches against ~15 hardcoded legacy templates via
Levenshtein distance and silently falls back to a bare `{{ .Prompt }}` passthrough when
nothing matches (logged only at `slog.Debug`, invisible by default) — exactly what had
been observed (see `2026-07-24-session-cleanup-and-scope-calls.md` for the original
"deliberately out of scope" decision this supersedes for 3 of 4 models).

**Real fix**: Ollama's own hand-written `RENDERER`/`PARSER` Modelfile directives
(independent of `TEMPLATE`/GGUF auto-detection), confirmed by fetching Ollama's own
official model configs from the registry API (no weights downloaded):
`qwen3.6-35b-a3b-gguf` and `qwen3.6-27b-gguf` -> `RENDERER qwen3.5` / `PARSER qwen3.5`;
`glm-4.7-flash-gguf` -> `RENDERER glm-4.7` / `PARSER glm-4.7`. Applied via `docker exec
ollama ollama create <name> -f <Modelfile>` (re-registers in place, reuses the existing
blob, no download) and verified with a real live `/v1/chat/completions` request with a
`tools` array — correct structured `tool_calls`, `<think>` content cleanly split into its
own `reasoning` field instead of leaking into `content`.

**`gemma-4-26b-a4b-gguf` remains genuinely blocked**: the `gemma4` renderer/parser doesn't
exist in this box's pinned Ollama 0.17.7 binary (Ollama's own official model metadata says
`requires: 0.20.0`, independently confirmed absent from the `v0.17.7` source) — fixable
only by upgrading Ollama's version, which is an explicit hard stop (a real behavior-change
decision affecting every registered model, not a drive-by version bump). Left for a human
decision.

**Not yet done at time of writing**: `scripts/benchmark_orchestrator.py` still hard-skips
every `ollama-*` engine build unconditionally — the skip logic needed updating to allow
the 3 now-fixed models through (while still skipping Gemma-4's Ollama build) before the
next full sweep.
