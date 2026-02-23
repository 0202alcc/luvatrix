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
- A filesystem alias `luvatrix-core/` points to the same core source for clarity.
