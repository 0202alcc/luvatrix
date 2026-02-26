# macOS Fallback Smoke Test

Use this to validate the clean fallback present path (no experimental Vulkan):

```bash
unset LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN
unset LUVATRIX_ENABLE_LEGACY_CAMETAL_FALLBACK
uv run --python 3.14 python examples/app_protocol/run_full_suite_interactive.py --aspect stretch --force-fallback
```

Expected:

1. Window renders animated content (not black/blank).
2. Terminal logs include `macOS present path active: fallback_clean`.
3. No CoreAnimation warning about changing `contents` on `CAMetalLayer`.

Emergency legacy path (debug only):

```bash
LUVATRIX_ENABLE_LEGACY_CAMETAL_FALLBACK=1 \
uv run --python 3.14 python examples/app_protocol/run_full_suite_interactive.py --aspect stretch --force-fallback
```
