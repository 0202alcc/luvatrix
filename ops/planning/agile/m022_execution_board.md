# R-022 Execution Board

Milestone: `R-022` Render copy elimination  
Branch: `codex/m-r-022-frame-copy-reduction`  
Framework: `gateflow_v1`

## Task Chain
`T-2201 -> T-2202 -> T-2203 -> T-2204`

## Current Placement
- `Intake`: none
- `Success Criteria Spec`: complete in task metadata (`tasks_master.json`)
- `Safety Tests Spec`: complete in task metadata (parity + deterministic ordering requirements)
- `Implementation Tests Spec`: complete in task metadata (pytest + perf suite commands)
- `Edge Case Tests Spec`: in progress (`T-2204` parity expansion added; broader edge coverage pending)
- `Prototype Stage 1`: complete
- `Prototype Stage 2+`: `T-2201`, `T-2202`, `T-2203`
- `Verification Review`: `T-2204`
- `Integration Ready`: none
- `Done`: none
- `Blocked`: none

## Evidence (Branch-Level)
1. `python3 -m pytest tests/test_window_matrix_protocol.py tests/test_display_runtime.py -q` -> `22 passed`.
2. `python3 -m pytest tests/test_macos_vulkan_backend.py -k "upload_rgba_to_staging_supports_cffi_buffer_return or upload_frame_stretches_to_swapchain_extent_when_enabled or upload_frame_preserve_aspect_letterboxes" -q` -> `3 passed`.
3. `PYTHONPATH=. python3 tools/perf/run_suite.py --scenario render_copy_chain --samples 60 --width 1600 --height 1000 --out artifacts/perf/render_copy_candidate.json` -> deterministic output emitted.
4. `PYTHONPATH=. python3 ...` micro-metric snapshots:
   - `artifacts/perf/render_copy_r022_op_deltas.json`
   - `artifacts/perf/render_copy_r022_snapshot_delta.json`
5. `PYTHONPATH=. python3 -m pytest tests -k "revision or frame_correctness" -q` -> `3 passed, 341 deselected`.

## Notes
- `Done` is intentionally empty; milestone is not merged to `main` and main-gate checks are not complete.
- `uv` panicked in this environment during audit (`system-configuration ... Attempted to create a NULL object`), so Python command fallback was used for local evidence generation.
