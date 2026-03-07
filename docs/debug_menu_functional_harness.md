# R-040 Closeout Harness

Milestone: `R-040` macOS Debug Menu Functionalization (Full Actions)

## Metric
- Metric ID: `r-040-closeout-v1`
- Go threshold: `>= 90`
- Hard No-Go conditions:
  - Any debug action remains stub/no-op without explicit disabled rationale.
  - Any menu click path can crash process.
  - Replay/frame-step/export determinism checks fail.
  - Kill-switch fails to safely disable functional action wiring.

## Required Evidence
- `ops/planning/closeout/r-040_closeout.md`
- `artifacts/debug_menu/r040_smoke/manifest.json`
- Screenshot/recording/bundle manifests in runtime artifacts.

## Required Commands
1. `PYTHONPATH=. uv run --with pytest pytest tests -k "debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle or macos_menu_integration" -q`
2. `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render macos --ticks 120`
3. `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/input_sensor_logger --render macos --ticks 120`
4. `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
5. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
6. `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id R-040`
