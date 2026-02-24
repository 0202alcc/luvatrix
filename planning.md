# Luvatrix Phase 1 Plan and Status

## TL;DR
Luvatrix now has a working app protocol runtime, matrix protocol, HDI/sensor threads, macOS visualizer path (fallback + experimental Vulkan), audit pipeline, and protocol governance. The next major work is production-hardening and platform expansion.

## 1. Current Implemented Scope

### 1.1 Core Runtime
1. `WindowMatrix` protocol is implemented (`H x W x 4`, `torch.uint8`) with atomic write batches.
2. `call_blit` event flow is implemented end-to-end through `DisplayRuntime`.
3. `UnifiedRuntime` runs app lifecycle + display + HDI + sensors in one loop.
4. App lifecycle contract is implemented: `init(ctx)`, `loop(ctx, dt)`, `stop(ctx)`.

### 1.2 App Protocol
1. `app.toml` + Python entrypoint loader is implemented.
2. Capability gating is enforced for matrix writes, HDI events, and sensors.
3. Protocol version governance is enforced with compatibility checks.
4. Security controls are implemented:
- denied capability access returns structured `DENIED` responses.
- sensor read rate limiting.
- sensor data sanitization/quantization unless high-precision capability is granted.

### 1.3 Platform Targeting in App Manifests
1. Apps can declare optional `platform_support` (OS allowlist).
2. Apps can declare `[[variants]]` with `id`, `os`, optional `arch`, optional `module_root`, optional `entrypoint`.
3. Runtime resolves and loads only the host-compatible variant.
4. Variant resolution is deterministic and path-confined (`module_root` cannot escape app dir).

### 1.4 HDI
1. HDI thread is implemented.
2. macOS native HDI source exists as a first-class module.
3. Keyboard/mouse/trackpad events are window-gated.
4. Pointer coordinates are normalized to window-relative values.
5. Out-of-window/inactive cases are represented via `NOT_DETECTED`.

### 1.5 Sensors
1. Sensor manager thread is implemented with polling and status model.
2. Default safety sensors are enabled by default:
- `thermal.temperature`
- `power.voltage_current`
3. macOS providers exist for:
- thermal
- power/voltage/current
- motion
4. Sensor state model is implemented: `OK`, `DISABLED`, `UNAVAILABLE`, `DENIED`.

### 1.6 Energy Safety
1. Runtime energy safety controller is implemented.
2. It consumes thermal/power telemetry, computes `OK/WARN/CRITICAL`, and throttles frame pacing.
3. `enforce` mode gracefully stops runtime on sustained critical telemetry.
4. Policy thresholds are configurable via CLI.

### 1.7 Rendering (macOS)
1. macOS presenter + target are implemented.
2. Fallback layer-blit path works for stretch and preserve-aspect examples.
3. Experimental Vulkan path renders and handles resize flow better than earlier revisions.
4. Vulkan path remains marked experimental while long-tail stability hardening continues.

### 1.8 Audit Pipeline
1. JSONL and SQLite sinks are implemented.
2. Capability, sensor, and energy-safety events can be persisted.
3. Report/prune CLI commands exist.

### 1.9 Testing and CI
1. Deterministic unit/integration suite is implemented and passing.
2. Coverage includes app runtime, protocol governance, sensor manager, HDI behavior, renderer integration with recording backend, and energy safety.
3. Guarded macOS GUI smoke workflow exists (flag-gated in CI).

## 2. Supported Developer Contract (Phase 1)

### 2.1 Required App Layout
```text
my_app/
├── app.toml
└── app_main.py
```

### 2.2 Required Manifest Fields
1. `app_id`
2. `protocol_version`
3. `entrypoint`
4. `required_capabilities`
5. `optional_capabilities`

### 2.3 Optional Manifest Fields
1. `min_runtime_protocol_version`
2. `max_runtime_protocol_version`
3. `platform_support`
4. `[[variants]]`

### 2.4 Core AppContext APIs
1. `submit_write_batch(batch)`
2. `poll_hdi_events(max_events)`
3. `read_sensor(sensor_type)`
4. `read_matrix_snapshot()`

## 3. What Is Still Open

1. Promote macOS Vulkan path from experimental to production-ready default.
2. Add robust retention/rotation/reporting tooling for audit stores.
3. Add richer consent UX and policy lifecycle for capabilities.
4. Add guarded OS-level end-to-end smoke strategy for more macOS environments.
5. Prepare shared Vulkan compatibility layer for non-macOS future backends.
6. Implement additional OS backends by reusing common runtime/protocol and shared Vulkan utilities.

## 4. Non-Goals for Current Phase

1. Full web renderer implementation (stub remains acceptable for now).
2. iOS/Android backend rollout in this phase.
3. Replacing protocol model with out-of-process app sandboxing in this phase.

## 5. Immediate Next Milestones

1. Vulkan stabilization pass (surface/swapchain/fence resilience and fallback parity).
2. Finalize app protocol docs with packaging/variant examples and compatibility policy.
3. Expand CI matrix with gated macOS GUI smoke and artifacted logs.
