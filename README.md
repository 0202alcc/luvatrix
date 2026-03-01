# Luvatrix

Custom app protocol + custom rendering protocol runtime in Python.

## Current Focus

Phase 1 is a macOS-first OS-level renderer:
- Window Matrix protocol (`H x W x 4` RGBA255, PyTorch)
- Vulkan presentation loop (`init -> loop -> stop`)
- HDI thread + Sensor manager thread
- In-process app protocol (`app.toml` + Python entrypoint)

## Install Notes

Base package:
```bash
pip install luvatrix
```

Optional Vulkan Python binding:
```bash
pip install "luvatrix[vulkan]"
```

Important:
- `pip` can install Python bindings, but it does not install the native Vulkan SDK/loader.
- On macOS, install Vulkan SDK or MoltenVK + Vulkan loader separately.
- `luvatrix` now prints a Vulkan preflight notice at runtime if these native components are missing.

## Planning Document

See `planning.md` for the integrated Phase 1 spec and visual TLDR protocol models.

## Repository Layout

- Core engine/runtime source lives in `luvatrix_core/`.
- In-repo UI contracts/components live in `luvatrix_ui/` (`text/`, `controls/`, `style/`).

## `luvatrix_ui` (In-Repo, v0)

`luvatrix_ui` is a first-party in-repo UI layer with explicit, future-extractable boundaries.

Current v0 surface:

- `TextRenderer` + text command/style contracts in `luvatrix_ui/text/renderer.py`.
- `SVGRenderer` + `SVGComponent` contracts in `luvatrix_ui/controls/svg_renderer.py` and
  `luvatrix_ui/controls/svg_component.py`.
- `ButtonModel` state machine in `luvatrix_ui/controls/button.py`:
  `idle`, `hover`, `press_down`, `press_hold`, `disabled`.
- `ThemeTokens` + validation/default merging in `luvatrix_ui/style/theme.py`.

Runtime-side compiler:

- `MatrixUIFrameRenderer` in `luvatrix_core/core/ui_frame_renderer.py` compiles first-party
  component batches (including SVG) into matrix frame tensors for `WriteBatch` submission.

Interaction model:

- Consumes standardized HDI `press` phases (`down`, `hold_start`, `hold_tick`, `up`, `cancel`, etc.).
- Keeps runtime/platform internals out of `luvatrix_ui`; integrations should adapt events/renderers at the boundary.

See:

- `docs/ui_component_protocol.md` for component contracts
- `docs/app_protocol.md` for runtime contract
- `docs/json_ui_compiler.md` for JSON page/lottie-oriented compiler design
- `docs/app_protocol_variants_guide.md` for variant routing examples and precedence
- `docs/app_protocol_compatibility_policy.md` for protocol support/deprecation policy
- `docs/app_protocol_operator_runbook.md` for operator troubleshooting and audit verification
- `docs/planes_protocol_v0.md` for the formal Planes JSON app-design schema (metadata, components, interactions, scripts, viewport semantics)
- `docs/app_protocol_v2_superset_spec.md` for protocol-v2 runtime/adapters/process-lane contract
- `docs/app_protocol_v2_conformance_matrix.md` for v1/v2 test matrix and CI gate commands
- `docs/app_protocol_v2_migration.md` for migration path from v1 in-process apps to v2

## macOS Visualizer Examples

Run stretch mode:
```bash
uv run --python 3.14 python examples/macos_visualizer/stretch_mode.py
```

Run preserve-aspect mode (black bars when needed):
```bash
uv run --python 3.14 python examples/macos_visualizer/preserve_aspect_mode.py
```

Run the full interactive suite app-protocol example (runs until window closes):
```bash
uv run --python 3.14 python examples/app_protocol/run_full_suite_interactive.py --aspect stretch
uv run --python 3.14 python examples/app_protocol/run_full_suite_interactive.py --aspect preserve
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

Protocol-v2 + Planes proof-of-concept app:
```bash
PYTHONPATH=. uv run --python 3.14 python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 300
```

Media transport lab (image + animated video rendering with aspect-ratio preserve and transport controls):
```bash
uv run --python 3.14 python main.py run-app examples/media_transport_lab --render macos --width 960 --height 540
```

Choose which sensors to log:
```bash
uv run --python 3.14 python examples/app_protocol/run_input_sensor_logger.py \
  --simulate-hdi \
  --sensor thermal.temperature \
  --sensor power.voltage_current
```

Additional available sensor metadata types:
`sensor.motion`, `camera.device`, `microphone.device`, `speaker.device`.

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

App manifests can now include optional `platform_support` and `[[variants]]` blocks so runtime picks only the host-compatible variant entrypoint/module root.

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

Enable runtime energy safety monitoring (throttles on warn, can enforce shutdown on sustained critical telemetry):
```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger \
  --sensor-backend macos \
  --energy-safety monitor
```

Enforce shutdown instead of monitor-only mode:
```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger \
  --sensor-backend macos \
  --energy-safety enforce \
  --energy-critical-streak 3
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
