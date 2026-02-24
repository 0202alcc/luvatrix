# Luvatrix

Custom app protocol + custom rendering protocol runtime in Python.

## Current Focus

Phase 1 is a macOS-first OS-level renderer:
- Window Matrix protocol (`H x W x 4` RGBA255, PyTorch)
- Vulkan presentation loop (`init -> loop -> stop`)
- HDI thread + Sensor manager thread
- In-process app protocol (`app.toml` + Python entrypoint)

## Planning Document

See `planning.md` for the integrated Phase 1 spec and visual TLDR protocol models.

## Repository Layout

- Core engine/runtime source lives in `luvatrix_core/`.

## macOS Visualizer Examples

Run stretch mode:
```bash
uv run --python 3.14 python examples/macos_visualizer/stretch_mode.py
```

Run preserve-aspect mode (black bars when needed):
```bash
uv run --python 3.14 python examples/macos_visualizer/preserve_aspect_mode.py
```

Force experimental Vulkan path:
```bash
LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN=1 uv run --python 3.14 python examples/macos_visualizer/stretch_mode.py
```

Force fallback layer-blit path:
```bash
unset LUVATRIX_ENABLE_EXPERIMENTAL_VULKAN
uv run --python 3.14 python examples/macos_visualizer/stretch_mode.py
```

Quick Vulkan environment probe (no window):
```bash
uv run --python 3.14 python examples/macos_visualizer/vulkan_probe.py
```

## App Protocol Example

Minimal input + sensor logger app:
```bash
uv run --python 3.14 python examples/app_protocol/run_input_sensor_logger.py --simulate-hdi --simulate-sensors
```

Choose which sensors to log:
```bash
uv run --python 3.14 python examples/app_protocol/run_input_sensor_logger.py \
  --simulate-hdi \
  --sensor thermal.temperature \
  --sensor power.voltage_current
```

Open a macOS logger window and report real mouse hover coordinates (window-relative only, gated by active/focused window):
```bash
uv run --python 3.14 python examples/app_protocol/run_input_sensor_logger.py \
  --open-window \
  --sensor thermal.temperature \
  --sensor power.voltage_current
```

Notes:
- `--simulate-hdi` intentionally emits synthetic keyboard events (`key='a'`) for test visibility.
- With `--open-window` and without `--simulate-hdi`, logger emits real window-gated mouse and keyboard input.

## Unified Runtime CLI

Run any app protocol folder (`app.toml` + entrypoint) headless:
```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render headless --ticks 300
```

Run it with macOS window rendering:
```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render macos --width 640 --height 360
```

Use real macOS sensor providers:
```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render headless --sensor-backend macos
```

Persist audit events to SQLite or JSONL:
```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --audit-sqlite ./.luvatrix/audit.db
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --audit-jsonl ./.luvatrix/audit.jsonl
```

With the logger example, you can explicitly include motion:
```bash
uv run --python 3.14 python examples/app_protocol/run_input_sensor_logger.py \
  --open-window \
  --sensor sensor.motion \
  --sensor thermal.temperature \
  --simulate-sensors
```
