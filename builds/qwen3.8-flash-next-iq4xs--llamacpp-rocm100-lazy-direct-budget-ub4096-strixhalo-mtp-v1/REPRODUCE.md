# Reproducing `qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-ub4096-strixhalo-mtp-v1`

Rejected candidate, kept for the record — see `build.yaml` for the measurement that
rejected it. This is `...-budget-mmproj-effort-medium-strixhalo-mtp-v1` with `-b/-ub`
changed from `16384` to `4096` and nothing else. Same image, same weights, same two
non-obvious gotchas (`HSA_OVERRIDE_GFX_VERSION` forced empty, explicit `/dev/kfd`
and `/dev/dri` device mounts) as every other build in this family — see the base
build's `REPRODUCE.md` for the full explanation of both.

```sh
sudo -n /run/current-system/sw/bin/modelctl up --exclusive qwen3.8-flash-next-iq4xs--llamacpp-rocm100-lazy-direct-budget-ub4096-strixhalo-mtp-v1
```

Port `8197`. Superseded by `...-ub8192-cram14g-strixhalo-mtp-v1` — start there instead.
