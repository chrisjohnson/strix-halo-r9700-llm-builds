---
id: 2026-08-09-ornith-thinkingcap-q8-only-no-mtp
date: 2026-08-09
source: "HF repos khudgins/Ornith-1.0-35B-ThinkingCap-GGUF + khudgins/Ornith-1.0-35B-ThinkingCap, khudgins/ornith-thinking-cap (github), singulared/Ornith-1.0-35B-MTP-GGUF, chat with repo author on HF, verified by direct fetch"
tags: [ornith, thinkingcap, mtp, llamacpp, qwen, speculative-decoding, model-catalog]
status: active
---

# Ornith ThinkingCap fork is Q8_0/f16-only and drops the MTP head — not a drop-in for the q4+MTP build

**Finding**: `khudgins/Ornith-1.0-35B-ThinkingCap-GGUF` (a reasoning-token-compression
LoRA fork of the Ornith 35B coding model, thinking-cap tagged) ships **only Q8_0 (36.9
GB) and f16 (65 GB) GGUFs — no Q4 variant exists anywhere on HF.** It also **drops the
Qwen3.5 MTP head** ("for llama.cpp compatibility" per the card), so it cannot serve as a
drop-in replacement for the project's standing `ornith-1.0-35b-mtp-q4--llamacpp-vulkan-radv`
build (Q4_K_M body + Q8 MTP head, ~20.55 GB on disk, ~63-66 tok/s at 0.859 draft accept
via llama.cpp native MTP).

Two separately-disqualifying gaps: (1) footprint — a Q8-only ThinkingCap (~36.9 GB)
residents larger than the q4 body and reintroduces the co-residency pressure that already
caused an OOM incident; (2) throughput — no MTP head means the 1.44x speculative-decoding
speedup (0.859 accept) is lost, dropping the 35B from ~63-66 tok/s back toward ~50.

**MTP graft would be buildable but unvalidated**: the author's merge recipe
(`tools/merge_35b.py` + `tools/fix_mtp.py` in `github.com/khudgins/ornith-thinking-cap`,
MIT) documents zeroing `mtp_num_hidden_layers` before conversion precisely because a
nonzero default produces a phantom unloadable `nextn` block. The donor head already exists
on-box at `/var/lib/ai-models/llamacpp-ornith-1.0-35b-mtp-q8/ornith-1.0-35b-MTP-Q8_0.gguf`
(37.8 GB), and singulared's documented recipe ("Q8_0 build above as the donor so the head
keeps its Q8 precision on top of a Q4_K_M body") shows the Q4_M build path is mechanical.
But the head is calibrated against base-Ornith hidden states, and ThinkingCap's LoRA
shifts attention projections, so **graft acceptance on ThinkingCap weights is unmeasured
— it needs a smoke test before trusting it.**

**Decision**: Chris elected to **skip ThinkingCap for now** (2026-08-09). No download was
made. The build is technically feasible via the Q8_0 download (36.9 GB) + MTP re-graft +
Q4_K_M re-quant, but the combination of Q8-only availability, MTP-drop, and unvalidated
graft acceptance made it not worth pulling. If revisited: the graft recipe above is the
path, and it should start with a MTP-acceptance smoke test, not a full deploy.

**Methodology**: direct verification against the HF model card and repo tree
(`.gitattributes`/README/Q8_0/f16 only), the author's own merge scripts on GitHub, and
singulared's MTP-graft recipe on HF — no unverified third-party claims. Filenames/sizes
confirmed by HEAD requests to HF CDN and the on-box donor file listing.
