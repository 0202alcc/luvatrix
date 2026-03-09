# Planes v2 Training Tutorial

This tutorial walks through the 10 training projects in increasing complexity.

## Recommended Order

1. `hello_plane`
2. `coordinate_playground`
3. `camera_overlay_basics`
4. `multi_plane_layout`
5. `scroll_and_pan_plane`
6. `interactive_components`
7. `sensor_status_dashboard`
8. `input_sensor_overlay_logger`
9. `debug_capture_workflow`
10. `planes_v2_poc_plus`

## Project Guide

### 1) `hello_plane` (Level 0)
What it showcases:
- Minimal Planes v2 app structure
- Basic event handler wiring
- Theme toggle interaction

### 2) `coordinate_playground` (Level 0)
What it showcases:
- Pointer event capture
- Coordinate mapping into app state
- Deterministic interaction state output

### 3) `camera_overlay_basics` (Level 1)
What it showcases:
- Camera overlay components
- Overlay visibility/state toggles
- Separation of world content vs overlay UI

### 4) `multi_plane_layout` (Level 1)
What it showcases:
- Multiple active planes in a route
- Plane focus switching interactions
- Layered layout composition

### 5) `scroll_and_pan_plane` (Level 2)
What it showcases:
- Viewport + scrollable content
- Scroll/pan handler behavior
- Scroll telemetry capture in state/artifacts

### 6) `interactive_components` (Level 2)
What it showcases:
- Interactive component mode transitions
- Repeated action sequencing
- Deterministic UI state progression

### 7) `sensor_status_dashboard` (Level 3)
What it showcases:
- Sensor-like status refresh flow
- Dashboard-style state aggregation
- Repeatable telemetry snapshots

### 8) `input_sensor_overlay_logger` (Level 3)
What it showcases:
- Combined input + sensor logging
- Overlay logging workflow
- Event ledger style state tracking

### 9) `debug_capture_workflow` (Level 4)
What it showcases:
- Debug tooling workflow simulation
- Screenshot/record/replay/frame-step/perf-hud/bundle actions
- Validation of complete debug action contracts

### 10) `planes_v2_poc_plus` (Level 5)
What it showcases:
- Route-oriented Planes v2 app flow
- `/home`, `/settings`, `/analytics` navigation behavior
- Multi-route validation and final integration pattern

## How To Run One Project

Visualize in macOS renderer:

```bash
PYTHONPATH=. uv run --python 3.14 python main.py run-app examples/planes_v2/<project_id> --render macos --width 960 --height 540 --fps 60 --ticks 1800
```

Run deterministic validation artifact generation:

```bash
PYTHONPATH=. uv run python examples/planes_v2/<project_id>/app_main.py --validate
```
