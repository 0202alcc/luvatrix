# App Protocol v1 -> v2 Migration Guide

## Goal

Move apps to protocol v2 without breaking v1 support, and align with current deterministic performance-path behavior.

## Path

1. Keep existing v1 app manifest and lifecycle working.
2. Add v2 fields incrementally.
3. Optionally migrate to process runtime lane.
4. Validate incremental-present/full-frame parity and sensor cached-read expectations.

## Step 1: Keep current in-process mode

```toml
protocol_version = "2"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []

[runtime]
kind = "python_inproc"
```

Notes for existing apps:

1. No lifecycle signature changes are required (`init/loop/stop` unchanged).
2. If app uses Planes runtime state directly, `incremental_present_enabled` defaults to `true`.
3. Use one-shot `force_full_invalidation=true` only for targeted parity or recovery frames.

## Step 2: Move to Python process lane

```toml
protocol_version = "2"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []

[runtime]
kind = "process"
transport = "stdio_jsonl"
command = ["python", "-u", "worker.py"]
```

## Step 3: Implement worker interface

Worker must handle:

1. `host.hello` -> respond `app.init_ok`
2. `host.tick` -> respond `app.commands`
3. `host.stop` -> respond `app.stop_ok`

Reference SDK:

- `luvatrix_core/core/process_sdk.py`

## Step 4: Validate performance-path compatibility

Incremental-present / invalidation checks:

1. `partial_dirty` mode should activate for safe integer scroll + dirty-strip updates.
2. `full_frame` fallback should activate when incremental safety conditions fail.
3. Escape hatch should force one full frame, then clear automatically.

Sensor fast-path / cached-path checks:

1. App reads are capability-gated and rate-limited before cache lookup.
2. Reads return cached sample values from sensor manager thread.
3. No hard sample TTL expiry is enforced; consumers should use `ts_ns` and `sample_id` freshness checks.

Vulkan transfer-path safety checks (if using macOS render path):

1. Staging map behavior is deterministic in persistent and transient modes.
2. Upload-image reuse path does not change frame semantics.
3. Swapchain invalidation debounce and fallback behavior are enabled for resilience.

## Operator rollout sequence

1. Baseline run with defaults.
2. Run parity pass with `LUVATRIX_INCREMENTAL_PRESENT_ENABLED=0` (force full-frame path).
3. Optionally enable `LUVATRIX_ENABLE_REVISIONED_SNAPSHOT=1` and compare deterministic revision-order output.
4. For Vulkan operators, keep debounced swapchain recreate enabled and validate fallback path readiness.

## Verification

```bash
PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py
PYTHONPATH=. uv run pytest tests/test_display_runtime.py -k "revision_snapshot_flag or parity or coalesces_to_latest_revision"
PYTHONPATH=. uv run pytest tests/test_planes_runtime.py -k "incremental_present or invalidation_escape_hatch or scroll_visual_parity"
PYTHONPATH=. uv run pytest tests/test_sensor_manager.py tests/test_app_runtime.py -k "sensor"
PYTHONPATH=. uv run pytest tests/test_macos_vulkan_backend.py -k "persistent_map or transient_mode_maps_each_frame or upload_image_reuse or swapchain_invalidation"
```
