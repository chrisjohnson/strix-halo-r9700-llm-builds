# Occamy-1.0 MTP Q5_K_M R9700 Benchmark Results

**Build:** `occamy-1.0-mtp-q5--llamacpp-vulkan-radv-r9700-mtp-v1`
**Hardware:** AMD Ryzen AI Max+ 395 / Strix Halo, R9700 eGPU (32 GiB GDDR6)
**Engine:** llama.cpp (kyuz0/amd-strix-halo-toolboxes:vulkan-radv, b10687/c841aeeb8)
**Date:** 2026-09-28

## Q5 K5_M Weight Specs
- **File:** `occamy-1.0-mtp-Q5_K_M.gguf`
- **Size:** 25,347,532,576 bytes (~23.6 GiB)
- **Quantization:** Q5_K_M (self-grafted MTP)
- **VRAM used:** ~30 GiB / 31.86 GiB (with q4_0 KV, np 3, 262144 tokens/slot)
- **GTT spill:** ~3 GiB

## Benchmark Results

### Prefill (single forward pass, all prompt tokens)
| Context | Q5_K_M (this build) | Q4_K_M (v2 baseline) | Delta |
|---------|---------------------|----------------------|-------|
| 8k (~9,354 tok) | **1,425 tok/s** | 2,190 tok/s | -35% |
| 32k (~35,255 tok) | **1,008 tok/s** | 1,641 tok/s | -39% |

### Decode (256 tokens generated, measured via /v1/chat/completions)
| Context | Q5_K_M (this build) | Q4_K_M (v2 baseline) | Delta |
|---------|---------------------|----------------------|-------|
| 0 (cold) | **119.3 tok/s** | 87 tok/s | +37% |
| 16,384 | **96.8 tok/s** | 80 tok/s | +21% |

### MTP Draft Acceptance (Q5_K_M)
| Context | Draft accepted | Acceptance rate |
|---------|---------------|-----------------|
| 0 (cold) | 160/187 avg | ~85% |
| 16,384 | 146/206 avg | ~71% |

## Analysis

**Why prefill is slower on Q5:** The Q5_K_M weights are 25.3 GiB vs Q4_K_M's 20.2 GiB (+25%). Prefill processes all prompt tokens in a single forward pass, so the larger weight matrix means more memory bandwidth is consumed per token. The ~35-39% prefill slowdown closely matches the weight size increase.

**Why decode is faster on Q5:** The higher quantization quality of Q5_K_M vs Q4_K_M means the MTP draft head predicts tokens more accurately, leading to higher draft acceptance rates (85% vs ~73% on Q4). Since MTP speculative decoding accepts draft tokens without running the full model, higher acceptance = fewer full model forward passes = faster decode. The ~37% decode improvement at ctx 0 is significant.

**Tradeoff summary:**
- Prefill: Q4 wins (-35% at 8k, -39% at 32k)
- Decode: Q5 wins (+37% at ctx 0, +21% at ctx 16384)
- For agentic workloads (long conversations with incremental prefill), the decode improvement likely outweighs the prefill cost, especially since the prefill at 8k/32k is still very fast (>1000 tok/s)

## Methodology

- **Prefill:** Sent long-context prompts to `/completion` with `n_predict=1`, measured `prompt_per_second` from llama.cpp's timing response. 3 runs, averaged.
- **Decode:** Used `/v1/chat/completions` with `ignore_eos=true`, `max_tokens=256`. Measured `predicted_per_second` from the `timings` field. 5 runs, averaged.
- **Tools:** `llama-server` with `--spec-type draft-mtp --spec-draft-n-max 2 --spec-draft-p-min 0.3 -np 3 --kv-unified --kv-unified-per-slot 262144 -ctk q4_0 -ctv q4_0 --cache-ram 32768`
- **Note:** Q4 v2 baseline numbers from `builds/occamy-1.0-mtp-q4--llamacpp-vulkan-radv-r9700-mtp-v2/build.yaml` (measured with `llm-inference-bench`'s `llm_decode_bench.py`, which uses the SGLang/vLLM API format but reports the same tok/s metrics).
