# App Protocol Compatibility Policy

This policy defines version compatibility, deprecation lifecycle, and migration requirements for first-party Luvatrix apps.

## 1. Protocol Support Matrix

Current runtime policy:

| Runtime date | Runtime protocol version | Supported manifest protocol versions | Deprecated but accepted |
| --- | --- | --- | --- |
| 2026-03-03 | `2` | `1`, `2` | `1` |

Interpretation:

1. `protocol_version = "2"` is accepted without warning.
2. `protocol_version = "1"` is accepted with deprecation warning.
3. Any other manifest protocol version is rejected.

## 2. Runtime Bounds Behavior (`min`/`max`)

App manifests may set:

1. `min_runtime_protocol_version`
2. `max_runtime_protocol_version`

Current runtime uses protocol `2` and applies checks in this order:

1. reject if `manifest.protocol_version` is unsupported
2. reject if runtime version is below `min_runtime_protocol_version`
3. reject if runtime version is above `max_runtime_protocol_version`
4. allow and warn only when version is accepted but marked deprecated

Examples:

```toml
# accepted on runtime protocol 2
protocol_version = "2"
min_runtime_protocol_version = "2"
max_runtime_protocol_version = "2"
```

```toml
# rejected on runtime protocol 2 (runtime below app minimum)
protocol_version = "2"
min_runtime_protocol_version = "3"
```

```toml
# rejected on runtime protocol 2 (runtime above app maximum)
protocol_version = "2"
max_runtime_protocol_version = "0"
```

## 3. Planes Schema Capability Policy (vNext extension)

When an app declares a `[planes]` table in `app.toml`, runtime applies additional compatibility checks:

1. `planes.schema_version` identifies authored Planes schema target.
2. `planes.min_schema_version` and `planes.max_schema_version` bound acceptable runtime schema support.
3. `planes.required_features` must be fully satisfied or app startup is rejected.
4. `planes.optional_features` may be unsupported without rejection.

Recommended current feature identifiers:

1. `multi_plane`
2. `camera_overlay`
3. `section_cuts`
4. `blend.absolute_rgba`
5. `blend.delta_rgba`
6. `route_activation`
7. `perf.culling_hints`

If `[planes]` is absent, legacy compatibility mapping remains in effect.

## 4. Performance-Path Compatibility Contract (R-022/R-023/R-025 + U-017 follow-up)

These runtime updates are behavior-tightening changes, not protocol-wire breaks.

Non-breaking guarantees:

1. Manifest schema and capability names are unchanged (`protocol_version` support remains `1` + `2`).
2. Existing app lifecycle hooks (`init/loop/stop`) are unchanged.
3. Existing operators can keep current launch commands and receive deterministic fallback behavior.

Determinism guarantees:

1. Display runtime coalesces pending blit events to newest revision to keep frame payload and revision aligned.
2. Optional revisioned snapshot path (`LUVATRIX_ENABLE_REVISIONED_SNAPSHOT=1`) preserves revision ordering parity with legacy snapshot path.
3. Incremental-present path has forced full-frame fallback on uncertainty boundaries (subpixel scroll, overlay activity, explicit invalidation).
4. HDI burst handling remains deterministic under queue coalescing and event-budget limits.

Operator-facing rollout toggles (all backward-compatible):

1. `LUVATRIX_INCREMENTAL_PRESENT_ENABLED` (default on): disable to force full-frame path.
2. `LUVATRIX_ENABLE_REVISIONED_SNAPSHOT` (default off): enable revision-matched snapshot fast-path.
3. `LUVATRIX_VK_PERSISTENT_STAGING_MAP` (default on): map-once staging behavior.
4. `LUVATRIX_VK_UPLOAD_IMAGE_REUSE` and `LUVATRIX_VK_TRANSFER_GROWTH` (default on): transfer allocation reuse/growth policies.
5. `LUVATRIX_VK_DEBOUNCE_SWAPCHAIN_RECREATE` (default on): recreate debounce guard.

Failure-containment guarantees:

1. Repeated swapchain-recreate failures trigger fallback layer-blit mode rather than protocol failure.
2. Invalidation escape hatch (`force_full_invalidation`) is one-shot and auto-clearing.
3. Sensor reads remain capability-gated and rate-limited before cached sample return.

## 5. Deprecation Lifecycle Policy

For future protocol revisions, use this lifecycle:

1. `Announce`: publish target removal and migration path in docs.
2. `Dual-support`: old version remains accepted but emits warnings.
3. `Default-shift`: examples/templates switch to the newer version.
4. `Removal`: old version is removed from supported set and rejected.

Governance requirements:

1. update compatibility docs and migration guide in the same change
2. add/refresh deterministic tests for acceptance, warnings, and rejection
3. include explicit milestone task evidence before marking release-complete

## 6. Migration Checklist

When bumping a first-party app to a new protocol version:

1. update `protocol_version` in `app.toml`
2. set `min_runtime_protocol_version` and `max_runtime_protocol_version` bounds intentionally
3. validate capabilities still map to supported names and semantics
4. run compatibility and app runtime tests
5. run app smoke command for representative runtime path
6. update app-level docs and runbook links

Performance-path migration checks (existing apps/operators):

1. Confirm app behavior is visually identical with:
   `incremental_present_enabled=true` and forced full invalidation in parity runs.
2. Verify sensors consumers handle `DENIED` (rate limit/capability) and `UNAVAILABLE` (no sample yet).
3. Verify perf telemetry ingestion accepts:
   `compose_mode`, dirty-rect counters, copy telemetry timing fields, HDI latency/coalescing counters.
4. If operating Vulkan path, verify fallback readiness under swapchain invalidation scenarios.

When adopting Planes schema vNext:

1. add `[planes]` metadata (`schema_version`, bounds, required/optional features)
2. confirm required feature set matches runtime support
3. verify compatibility mapping for legacy payloads is not relied on implicitly

## 7. Migration Example

Before:

```toml
protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = ["sensor.thermal"]
```

After (same runtime target, explicit bounds):

```toml
protocol_version = "1"
min_runtime_protocol_version = "1"
max_runtime_protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = ["sensor.thermal"]
```

Protocol v2 + Planes vNext example:

```toml
protocol_version = "2"
min_runtime_protocol_version = "2"
max_runtime_protocol_version = "2"

[planes]
schema_version = "0.2.0-dev"
min_schema_version = "0.1.0"
max_schema_version = "0.2.0-dev"
required_features = ["multi_plane", "camera_overlay", "blend.delta_rgba"]
optional_features = ["section_cuts", "route_activation"]
```

## 8. Verification Commands

Compatibility and bounds checks:

```bash
uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py -k "protocol or runtime_protocol"
```

Runtime integration coverage:

```bash
uv run pytest tests/test_unified_runtime.py tests/test_app_runtime.py
```

Planes/runtime safety smoke for current M-008 track:

```bash
PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py
```

Performance-path determinism checks:

```bash
PYTHONPATH=. uv run pytest tests/test_display_runtime.py -k "revision_snapshot_flag or parity or coalesces_to_latest_revision"
PYTHONPATH=. uv run pytest tests/test_planes_runtime.py -k "incremental_present or invalidation_escape_hatch or scroll_visual_parity"
PYTHONPATH=. uv run pytest tests/test_sensor_manager.py tests/test_app_runtime.py -k "sensor"
PYTHONPATH=. uv run pytest tests/test_macos_vulkan_backend.py -k "persistent_map or transient_mode_maps_each_frame or upload_image_reuse or swapchain_invalidation"
```
