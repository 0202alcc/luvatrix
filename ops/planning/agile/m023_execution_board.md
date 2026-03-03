# R-023 Execution Board

Milestone: `R-023` Vulkan transfer path efficiency  
Branch: `codex/m-r-023-transfer-latency`  
Framework: `gateflow_v1`

## Task Chain
`T-2401 -> T-2402 -> T-2403 -> T-2404`

## Current Placement
- `Intake`: none
- `Success Criteria Spec`: complete in task metadata (`tasks_master.json`)
- `Safety Tests Spec`: complete in task metadata (determinism + fallback parity requirements)
- `Implementation Tests Spec`: complete in task metadata (`pytest` + perf suite evidence commands)
- `Edge Case Tests Spec`: complete in task metadata (resize stress + swapchain invalidation)
- `Prototype Stage 1`: `T-2401`
- `Prototype Stage 2+`: `T-2402`, `T-2403`, `T-2404`
- `Verification Review`: none
- `Integration Ready`: none
- `Done`: none
- `Blocked`: none

## Evidence (Branch-Level)
1. `uv run pytest tests/test_macos_vulkan_backend.py -k "persistent_map or transient_mode_maps_each_frame or upload_image_reuse or swapchain_invalidation" -q`
2. `uv run pytest tests/test_display_runtime.py tests/test_planes_runtime.py -k "copy or telemetry" -q`
3. `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario resize_stress --samples 24 --width 640 --height 360 --out artifacts/perf/r023_resize_stress_candidate.json`
4. `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario all_interactive --samples 24 --width 640 --height 360 --out artifacts/perf/r023_interactive_candidate.json`

## Notes
- `Done` remains empty until merge to `main` and required checks pass on `main`.
- Planning writes (`planning_api.py --apply`) must run on `main`; this branch keeps implementation and dry-run planning commands only.
