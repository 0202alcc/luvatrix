# F-024 Execution Board - Sensor Backend Performance Modernization

Framework: `Luvatrix GateFlow (gateflow_v1)`
Milestone: `F-024`
Tasks: `T-2501`, `T-2502`, `T-2503`, `T-2504`

## Columns
1. `Intake`
2. `Success Criteria Spec`
3. `Safety Tests Spec`
4. `Implementation Tests Spec`
5. `Edge Case Tests Spec`
6. `Prototype Stage 1`
7. `Prototype Stage 2+`
8. `Verification Review`
9. `Integration Ready`
10. `Done`
11. `Blocked`

## Current Card Placement (Milestone Complete)

### Done
1. `T-2501` Profile sensor provider cost/jitter and classify fast-path vs cached metadata providers.
2. `T-2502` Introduce TTL caching for slow-changing metadata providers.
3. `T-2503` Replace high-cost subprocess sensor reads with direct/native API access where feasible.
4. `T-2504` Enforce capability/consent/audit parity tests for sensor modernization.

Completion evidence:
1. Merge to `main` completed from `codex/m-f-024-sensor-modernization`.
2. Main checks passed:
   - `uv run python tools/perf/run_suite.py --scenario sensor_polling --out artifacts/perf/sensor_polling_candidate_main.json`
   - `PYTHONPATH=. uv run pytest tests/test_sensor_manager.py tests/test_macos_sensors.py tests/test_sensor_modernization_parity.py tests/test_app_runtime.py tests/test_audit_sink.py tests/test_perf_tools.py -k "consent or capability or denial or sensor or perf" -q`
3. Planning API transitions applied stage-by-stage through `Done` with required `actuals` + `done_gate`.
4. Link validation passed:
   - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
