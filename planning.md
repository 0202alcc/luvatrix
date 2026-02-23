# Luvatrix Phase 1 Integrated Plan

## TLDR

### App Protocol (How To Build a Supported App)
A Luvatrix app is an in-process Python plugin with a manifest. The runtime loads it, enforces capabilities, and gives it an `AppContext` for HDI events, sensor data, and matrix writes.

```text
App Folder
└── my_app/
    ├── app.toml
    └── app_main.py

app.toml
  app_id = "media.simple"
  protocol_version = "1"
  entrypoint = "app_main:run"
  required_capabilities = ["window.write", "hdi.keyboard"]
  optional_capabilities = ["sensor.thermal", "sensor.power"]
```

```text
Build/Run Model
[app.toml + entrypoint]
        |
        v
[Luvatrix App Loader]
        |
        +--> validate manifest + protocol version
        +--> request runtime permissions
        v
[AppContext]
  - submit_write_batch(...)
  - poll_hdi_events(...)
  - read_sensor(...)
        |
        v
[Window Matrix Protocol] -> [Renderer Blit]
```

### Rendering Protocol (How Matrix Becomes a Window)
The renderer consumes a canonical RGBA255 matrix (`H x W x 4`, `torch.uint8`) and blits only when `call_blit` is raised by a committed write batch.

```text
App/Runtime Write Batch
   (single-writer lock, atomic commit)
                |
                v
      Window Matrix (RGBA255)
      shape: H x W x 4
      dtype: torch.uint8
                |
                v
        call_blit event raised
                |
                v
      Vulkan Main Render Loop
          init -> loop -> stop
                |
                v
        OS Surface Presentation
```

```text
OS Mapping (currently supported OS-level backend)
- macOS:
  Matrix tensor -> staging/upload -> Vulkan image -> swapchain present -> window
```

## 1. Goals

1. Standardize project/package name as `luvatrix`.
2. Deliver a macOS-first OS-level rendering runtime with Vulkan presentation.
3. Define a stable custom app protocol for compatible apps.
4. Add HDI and sensor threads with standardized schemas for future cross-device stability.
5. Keep iOS/android unchanged for now; web prototype is deprecated in-repo.

## 2. Runtime and Package Baseline

1. Python requirement: `>=3.14,<3.15`.
2. Tensor runtime: PyTorch.
3. Compute policy:
- Prefer AMD ROCm where available.
- Fallback to CPU.
- For macOS Phase 1, CPU tensor compute is expected while Vulkan handles presentation.

## 3. Rendering Protocol (Normative)

### 3.1 Canonical Window Matrix

1. Shape: `height x width x 4`.
2. Channels: `R,G,B,A`.
3. Type: `torch.uint8`.
4. Valid range: `0..255`.

Invalid channel behavior:
- Warn once per batch with offending location count.
- Replace offending pixels with `rgba(255,0,255,255)`.

### 3.2 Read Model

1. Any thread may read live matrix.
2. Direct no-copy unsafe handle is **internal only**.
3. App plugins use safe read interfaces.

### 3.3 Write Model

1. Single-writer lock.
2. Writer requests are validated and queued.
3. Commit is atomic per batch.
4. Successful commit raises `call_blit`.

Supported write operations:
1. `full_rewrite(tensor_h_w_4)`
2. `push_column(index, column_h_4)` (shift + evict, fixed size)
3. `replace_column(index, column_h_4)`
4. `push_row(index, row_w_4)` (shift + evict, fixed size)
5. `replace_row(index, row_w_4)`
6. `multiply(color_matrix_4x4)` (per-pixel RGBA transform + clamp)

### 3.4 Render Loop and Limits

1. Main thread runs Vulkan loop (`init`, `loop`, `stop`).
2. Loop waits for `call_blit`.
3. If deque empty, no blit.
4. Blits are event-driven with max FPS cap.

Warnings/errors:
1. Window larger than display: warning.
2. Window exceeding feasible compute/render budget (after warmup benchmark): error.

## 4. HDI Thread (macOS Phase 1)

### 4.1 Scope

1. Keyboard capture only while Luvatrix window is focused.
2. Mouse position only when window active.
3. If window inactive: return status `NOT_DETECTED`.
4. Force Touch is part of HDI stream as pressure events.

### 4.2 Event Contract

`HDIEvent` fields:
1. `event_id`
2. `ts_ns`
3. `window_id`
4. `device` (`keyboard|mouse|trackpad`)
5. `event_type`
6. `status` (`OK|NOT_DETECTED|UNAVAILABLE|DENIED`)
7. `payload` (typed object or `null`)

### 4.3 Concurrency and Throughput

1. Simultaneous inputs are handled via queued event stream.
2. Use bounded queue + move-event coalescing.
3. Never drop keyboard down/up transitions.

## 5. Sensor Manager Thread (macOS Phase 1)

### 5.1 Threading Model

1. One sensor manager thread.
2. Per-sensor async tasks/subscriptions inside manager.

### 5.2 Defaults and Permissions

1. Default enabled:
- thermal/temperature
- voltage/current
2. Other sensors are disabled by default.
3. App can request enable via manifest + runtime consent.
4. Disabling default safety sensors requires warning prompt and audit log.

### 5.3 Sensor Contract

`SensorSample` fields:
1. `sample_id`
2. `ts_ns`
3. `sensor_type`
4. `status` (`OK|DISABLED|UNAVAILABLE|DENIED`)
5. `value` (typed object or `null`)
6. `unit`

## 6. App Protocol (Normative)

### 6.1 Required Structure

```text
app/
├── app.toml
└── app_main.py
```

`app.toml` minimum:
1. `app_id`
2. `protocol_version`
3. `entrypoint` (`module:function`)
4. `required_capabilities`
5. `optional_capabilities`

### 6.2 Lifecycle

1. `init(ctx)`
2. `loop(ctx, dt)`
3. `stop(ctx)`

### 6.3 AppContext APIs

1. `submit_write_batch(batch)`
2. `poll_hdi_events(max_events)`
3. `read_sensor(sensor_type)`
4. Safe matrix read views.

## 7. Phase 1 Reference App

1. Build a media app with single file path parameter.
2. Images: Pillow.
3. Video frames: imageio-ffmpeg.
4. Convert decoded frames to RGBA255 and write through protocol ops.

## 8. Security and Stability Rules

1. No global keyboard capture by default.
2. Unsafe matrix reads are internal-only.
3. Capability grants/denials are logged.
4. Status enums are mandatory for missing/unavailable data.
5. Protocol version mismatch fails fast at app load.

## 9. Test and Acceptance Plan

1. Matrix invariants and invalid pixel replacement.
2. Atomic write batch correctness.
3. Blit trigger behavior and FPS cap enforcement.
4. HDI event ordering and inactive mouse `NOT_DETECTED` handling.
5. Sensor defaults, enable/disable, and warning/audit on safety disable.
6. End-to-end media app rendering through matrix protocol.

## 10. Implementation Sequence

1. Rename and package baseline (`luvatrix`, Python 3.14, torch dependency).
2. Implement matrix protocol core.
3. Integrate Vulkan main render loop on macOS.
4. Implement HDI thread.
5. Implement sensor manager thread.
6. Implement app protocol loader/lifecycle.
7. Build and validate media reference app.

## 11. Out of Scope (Phase 1)

1. iOS backend redesign.
2. Android backend redesign.
3. Web renderer redesign (legacy web prototype removed).
4. NVIDIA acceleration path.
