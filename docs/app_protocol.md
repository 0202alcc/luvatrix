# Luvatrix App Protocol (Phase 1)

## 1. App Package Layout

```text
my_app/
├── app.toml
└── app_main.py
```

`app.toml` required fields:

1. `app_id`
2. `protocol_version`
3. `entrypoint` (`module:symbol`)
4. `required_capabilities` (list[str])
5. `optional_capabilities` (list[str])

Optional protocol governance fields:

1. `min_runtime_protocol_version`
2. `max_runtime_protocol_version`

Optional platform routing fields:

1. `platform_support` (list[str], e.g. `["macos", "linux"]`)
2. `[[variants]]` entries with:
   `id`, `os`, optional `arch`, optional `module_root`, optional `entrypoint`

For apps that share one entrypoint across Apple platforms, prefer a simple support declaration:

```toml
platform_support = ["macos", "ios"]
```

Use variants only when a supported platform or architecture needs a different module root or entrypoint.

Variant routing behavior:

1. Runtime rejects app if host OS is not in `platform_support` (when provided).
2. Runtime selects the best matching variant for host `os/arch`.
3. Arch-specific matches are preferred over OS-only matches.
4. `module_root` is sandboxed to stay within app folder.

Install validation:

1. Base installs support manifest loading and headless app validation.
2. Optional renderers validate their extras before launch.
3. `run-app --render macos` requires the `macos` and `vulkan` extras.
4. `run-app --render macos-metal` requires the `macos` extra.
5. `run-app --render web` requires the `web` extra.

## 2. Lifecycle Contract

Entrypoint resolves to an object with:

1. `init(ctx) -> None`
2. `loop(ctx, dt: float) -> None`
3. `stop(ctx) -> None`

## 3. AppContext Contract

`AppContext` exposes:

1. `submit_write_batch(batch)` (requires `window.write`)
2. `poll_hdi_events(max_events)`
3. `read_sensor(sensor_type)`
4. `read_matrix_snapshot()`

Security rules:

1. Missing HDI capability returns event with `status=DENIED` and `payload=None`.
2. Missing sensor capability returns `SensorSample(status="DENIED")`.
3. Sensor reads are rate-limited (`sensor_read_min_interval_s`).
4. Sensor reads are non-blocking cached reads from `SensorManagerThread` (no provider I/O in app loop).
5. Sensor values are quantized unless `sensor.high_precision` capability is granted.

## 4. Capability Naming

Examples:

1. `window.write`
2. `hdi.keyboard`
3. `hdi.mouse`
4. `hdi.trackpad`
5. `sensor.thermal`
6. `sensor.power`
7. `sensor.motion`
8. `sensor.camera`
9. `sensor.microphone`
10. `sensor.speaker`
11. `sensor.high_precision`

## 5. Sensor Semantics

Default sensor status values:

1. `OK`
2. `DISABLED`
3. `UNAVAILABLE`
4. `DENIED`

macOS backend (current):

1. `thermal.temperature`
2. `power.voltage_current`
3. `sensor.motion`
4. `camera.device`
5. `microphone.device`
6. `speaker.device`

Deterministic read path:

1. `AppContext.read_sensor(sensor_type)` checks capability first.
2. If capability is missing, return `DENIED` immediately.
3. If capability is present but read interval is below `sensor_read_min_interval_s`, return `DENIED` immediately.
4. If checks pass, return current cached sample from `SensorManagerThread.read_sensor(sensor_type)`.

Fast-path and cached-path behavior:

1. Fast-path: app reads return current in-memory sample and do not call providers synchronously.
2. Cached-path: background sensor manager thread polls enabled providers at `poll_interval_s` and refreshes sample cache.
3. Default poll interval is implementation-dependent by launcher (`SensorManagerThread` default is `0.5s`; `main.py run-app` currently uses this default).

TTL/freshness behavior (current implementation):

1. No hard sample-expiry TTL is enforced in protocol runtime today.
2. Effective freshness window is the manager polling cadence (`poll_interval_s`) plus provider latency.
3. Before first successful poll, reads return `UNAVAILABLE` (or `DISABLED`/`DENIED` based on gate state).
4. Consumers must handle stale-but-valid cached values and rely on `ts_ns` + `sample_id` for freshness decisions.

## 6. HDI Semantics

Current devices:

1. `keyboard`
2. `mouse`
3. `trackpad`

Trackpad events (best effort):

1. `scroll`
2. `pinch`
3. `rotate`
4. `pressure`
5. `click`

All pointer/trackpad input is active-window gated and normalized to window-relative coordinates where applicable.

## 7. Protocol Governance

1. Runtime checks compatibility via protocol governance policy.
2. Unsupported versions fail fast.
3. Min/max runtime bounds can be expressed by app manifests.
4. Deprecation warnings are emitted for deprecated-but-supported versions.

## 8. Audit Pipeline

Audit sinks:

1. SQLite (`SQLiteAuditSink`)
2. JSONL (`JsonlAuditSink`)

Audit events include capability and sensor security decisions.

## 9. Energy Safety Controller

Runtime can consume hardware telemetry and apply protective pacing:

1. Reads `thermal.temperature` and `power.voltage_current`.
2. Normalizes values to Celsius and Watts.
3. Applies policy thresholds (`warn`, `critical`).
4. In `monitor` mode: logs state transitions and throttles loop pacing.
5. In `enforce` mode: gracefully stops app loop after sustained critical streak.

CLI knobs:

1. `--energy-safety off|monitor|enforce`
2. `--energy-thermal-warn-c`, `--energy-thermal-critical-c`
3. `--energy-power-warn-w`, `--energy-power-critical-w`
4. `--energy-critical-streak`
## 10. CI Smoke Strategy (macOS GUI)

Use a guarded smoke job:

1. Run only on macOS runners with GUI support.
2. Gate execution behind env var flag (default disabled).
3. Run short smoke command:
   `uv run --python 3.14+freethreaded python main.py run-app examples/app_protocol/input_sensor_logger --render macos --ticks 120 --fps 30`
4. Treat this as smoke (non-deterministic), keep deterministic unit/integration suite as required gate.

## 11. UI Component Protocol Note

For in-repo first-party UI components (`luvatrix_ui`), see:

- `docs/ui_component_protocol.md`

## 12. First-Party UI Frame API (v0)

Apps can compile first-party UI components into the next matrix frame via `AppContext`:

1. `begin_ui_frame(renderer, content_width_px=?, content_height_px=?, clear_color=?)`
2. `mount_component(component)` for each component
3. `finalize_ui_frame()` to compile/render and submit one `WriteBatch`

Notes:

1. This flow is app-protocol-side frame compilation, not display renderer behavior.
2. `content_width_px` / `content_height_px` should represent the displayable content area
   (excluding letterbox/black bars in preserve-aspect mode).
3. Text sizing ratios use displayable area dimensions.
4. `finalize_ui_frame()` requires `window.write` capability.
5. Runtime may submit full-frame or partial-dirty write batches (`FullRewrite`, `ShiftFrame + ReplaceRect`, or `ReplaceRect` set) based on incremental-present policy.
6. SVG components are compiled through batched SVG render commands with explicit target
   width/height; runtime renderers should rasterize directly at that target size.

## 13. Incremental-Present and Invalidation Policy (U-017/R-022/R-023/R-025 follow-up)

Planes runtime (`luvatrix_ui/planes_runtime.py`) applies deterministic present-mode selection:

1. `idle_skip`: no dirty regions and no required invalidation; no present submitted.
2. `partial_dirty`: localized dirty regions are emitted and patched (optionally with integer `scroll_shift`).
3. `full_frame`: full-frame compose path is used when incremental safety conditions are not met.

Incremental-present control:

1. `state["incremental_present_enabled"]` toggles incremental path at runtime.
2. Default comes from `LUVATRIX_INCREMENTAL_PRESENT_ENABLED` (default enabled).
3. When disabled, dirty updates are promoted to full-frame compose deterministically.

Invalidation escape hatch (one-shot):

1. Set `state["force_full_invalidation"] = true` to force next frame to `full_frame`.
2. Optional `state["force_full_invalidation_reason"]` is recorded in telemetry.
3. Escape hatch is consumed once per frame and auto-cleared:
   `force_full_invalidation -> false`, `force_full_invalidation_reason -> None`.

Full-frame fallback boundaries (current behavior):

1. First frame after init.
2. Theme or hover-signature changes.
3. Subpixel plane scroll deltas (cannot map to integer shift safely).
4. Bi-axial integer plane scroll in one frame (seam-avoidance fallback).
5. Active camera-overlay components during scroll-sensitive updates.
6. Explicit incremental disable or one-shot invalidation escape hatch.

Determinism and parity guarantees:

1. Dirty-rect normalization is sorted and deduplicated before submit.
2. Quantized scroll shift uses deterministic integer rounding (`-round(dx/dy)`).
3. Incremental vs forced-full scroll parity is validated in tests (`tests/test_planes_runtime.py`).
4. Revision alignment between `CallBlitEvent.revision` and presented frame is preserved by display-runtime event coalescing (`tests/test_display_runtime.py`).

Telemetry fields expected for this policy:

1. `compose_mode`: `idle_skip | partial_dirty | full_frame`
2. `dirty_rect_count`, `dirty_rect_area_px`, `dirty_rect_area_ratio`
3. `incremental_present_enabled`
4. `invalidation_escape_hatch_used`, `invalidation_escape_hatch_reason`
5. `copy_count`, `copy_bytes`, `copy_timing_ms.*`

## 14. JSON Page Compiler Expansion (Draft)

For JSON-driven app construction and future Figma/Lottie import support, use a compiler
pipeline that produces first-party component IR for `mount_component(...)`.

Recommended compiler stages:

1. parse JSON source
2. validate fields and value ranges
3. normalize defaults (frame, z-index, bounds, opacity)
4. bind action names to backend handler registry
5. emit deterministic component IR list

Detailed schema and examples:

- `docs/json_ui_compiler.md`

## 15. Component Ordering and Frame Rules

For compiler-produced components:

1. each component may declare its own coordinate `frame`
2. each component may declare `z_index` (draw order)
3. renderer draw order should be `z_index` ascending, then source order ascending
4. hit-testing order should be reverse draw order
5. `interaction_bounds` defaults to visual bounds and does not affect paint geometry

## 16. Backend Function Binding Contract

JSON components may define a `functions` object that maps interaction hooks to backend
function names (for example: `on_press`, `on_press_hold`, `on_hover_start`).

Recommended runtime behavior:

1. compile stores function names in IR
2. app init resolves names against backend handler registry
3. strict mode fails when a declared function is missing or non-callable
4. permissive mode warns and uses no-op handler

## 17. UI Generation Through MatrixUIFrameRenderer

`MatrixUIFrameRenderer` is app-protocol-side component-to-matrix compilation.

Per frame:

1. `begin_ui_frame(renderer, ...)` allocates/clears frame tensor
2. app mounts first-party components
3. `finalize_ui_frame()` converts components into text/SVG batch commands
4. renderer executes batch draws onto one RGBA frame tensor
5. runtime submits deterministic `WriteBatch` ops via full-frame or incremental dirty paths

This separation keeps display backend concerns out of component logic.

## 18. Recommended Documentation Set

For protocol/UI work, keep these documents aligned:

1. `docs/app_protocol.md` (runtime contract)
2. `docs/ui_component_protocol.md` (component contract)
3. `docs/json_ui_compiler.md` (JSON source and compile rules)
4. `docs/app_protocol_variants_guide.md` (variant routing and failure cases)
5. `docs/app_protocol_compatibility_policy.md` (version compatibility and deprecation policy)
6. `docs/app_protocol_operator_runbook.md` (operator commands and troubleshooting)
7. `docs/planes_protocol_v0.md` (JSON-first Plane/component schema standard)
8. `docs/app_protocol_v2_superset_spec.md` (v2 runtime/adapters/process-lane contract)
9. `docs/app_protocol_v2_conformance_matrix.md` (required test and CI matrix)
10. `docs/app_protocol_v2_migration.md` (v1 to v2 migration guide)

## 19. First-Party App Standardization Checklist

A first-party app is considered protocol-standardized only when all items below are true:

1. Manifest includes required fields:
   `app_id`, `protocol_version`, `entrypoint`, `required_capabilities`, `optional_capabilities`.
2. Protocol governance is explicit:
   use `min_runtime_protocol_version` / `max_runtime_protocol_version` when release bounds are required.
3. Variant routing is deterministic:
   use normalized `platform_support` and `[[variants]]` entries with stable IDs and non-escaping `module_root`.
4. Lifecycle object implements:
   `init(ctx)`, `loop(ctx, dt)`, `stop(ctx)`.
5. Capability gating assumptions are documented:
   expected `DENIED` behavior for missing HDI/sensor permissions is intentional and tested.
6. Operator runbook coverage exists:
   run commands, troubleshooting, and audit verification are documented.
7. CI/verification evidence includes protocol governance and app runtime variant tests.

Companion references:

1. `docs/app_protocol_variants_guide.md`
2. `docs/app_protocol_compatibility_policy.md`
3. `docs/app_protocol_operator_runbook.md`
4. `docs/planes_protocol_v0.md`
5. `docs/app_protocol_v2_superset_spec.md`
6. `docs/app_protocol_v2_conformance_matrix.md`
7. `docs/app_protocol_v2_migration.md`
