# R-039 Execution Board (GateFlow)

Milestone: `R-039`  
Name: `macOS Debug Menu Runtime Wiring (E2E)`

## Intake
- [x] `T-3290` [CLOSEOUT HARNESS] Define R-039 closeout metric and evidence harness
- [x] `T-3201` AppKit menu bootstrap + safe defaults
- [x] `T-3202` Debug menu action wiring to runtime handlers
- [x] `T-3203` Manifest policy integration in live macOS path
- [x] `T-3204` macOS menu safety + behavior smoke tests
- [x] `T-3205` Example app E2E menu smoke harness
- [x] `T-3206` Closeout gate + rollback controls
- [x] `T-3210` ObjC menu target lifecycle collision fix
- [x] `T-3211` R-039 macOS smoke preflight + structured manifest
- [x] `T-3212` R-039 environment bootstrap and runbook standardization
- [x] `T-3213` R-039 full revalidation and closeout packet refresh

## Success Criteria Spec
- [ ]

## Safety Tests Spec
- [ ]

## Implementation Tests Spec
- [ ]

## Edge Case Tests Spec
- [ ]

## Prototype Stage 1
- [ ]

## Prototype Stage 2+
- [ ]

## Verification Review
- [ ]

## Integration Ready
- [ ]

## Done
- [x] `T-3290` `T-3201` `T-3202` `T-3203` `T-3204` `T-3205` `T-3206` `T-3210` `T-3211` `T-3212` `T-3213`

## Blocked
- [ ] Live macOS run-app verification blocked in current environment by missing AppKit/PyObjC runtime.

## Verification Command Order
1. `uv sync --extra macos --extra vulkan`
2. `PYTHONPATH=. uv run --with pytest pytest tests -k "debug_menu_dispatch or debug_manifest_policy or macos_menu_integration" -q`
3. `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render macos --ticks 120`
4. `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/input_sensor_logger --render macos --ticks 120`
5. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
6. `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id R-039`
