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

Variant routing behavior:

1. Runtime rejects app if host OS is not in `platform_support` (when provided).
2. Runtime selects the best matching variant for host `os/arch`.
3. Arch-specific matches are preferred over OS-only matches.
4. `module_root` is sandboxed to stay within app folder.

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
4. Sensor values are quantized unless `sensor.high_precision` capability is granted.

## 4. Capability Naming

Examples:

1. `window.write`
2. `hdi.keyboard`
3. `hdi.mouse`
4. `hdi.trackpad`
5. `sensor.thermal`
6. `sensor.power`
7. `sensor.motion`
8. `sensor.high_precision`

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
   `uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render macos --ticks 120 --fps 30`
4. Treat this as smoke (non-deterministic), keep deterministic unit/integration suite as required gate.
