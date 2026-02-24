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
