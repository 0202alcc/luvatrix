# GateFlow Cost Rubric (v1)

Model-normalized effort scoring for task planning across different LLMs.

## Fields

1. `cost_components` (all `0..100`)
- `context_load`
- `reasoning_depth`
- `code_edit_surface`
- `validation_scope`
- `iteration_risk`
2. `cost_confidence` (`0..1`)
3. Derived by API (`--reestimate-cost`):
- `cost_score` (`0..100`)
- `cost_bucket` (`S|M|L|XL|XXL`)
- `stage_multiplier_applied`
- `cost_basis_version=gateflow_cost_v1`

## Base weighted formula

`cost_score_base =`

1. `0.20 * context_load`
2. `+ 0.25 * reasoning_depth`
3. `+ 0.20 * code_edit_surface`
4. `+ 0.20 * validation_scope`
5. `+ 0.15 * iteration_risk`

## Stage multipliers

1. `Intake`: `x0.60`
2. `Success Criteria Spec`: `x0.80`
3. `Safety Tests Spec`: `x0.90`
4. `Implementation Tests Spec`: `x0.90`
5. `Edge Case Tests Spec`: `x0.95`
6. `Prototype Stage 1`: `x1.00`
7. `Prototype Stage 2+`: `x1.10`
8. `Verification Review`: `x0.85`
9. `Integration Ready`: `x0.70`
10. `Done`: `x0.00`
11. non-GateFlow/legacy statuses: `x1.00`

## Buckets

1. `S`: `0..20`
2. `M`: `21..40`
3. `L`: `41..60`
4. `XL`: `61..80`
5. `XXL`: `81..100`

## Operating policy

1. `XL/XXL` should be split before entering `Prototype Stage 1`.
2. `cost_confidence < 0.35` should block prototype stages until specs are refined.
3. Transition to `Blocked` should lower confidence by `0.15` (floor `0.0`).

## Completion telemetry (required on Done transition)

Add to task when transitioning to `Done`:

1. `actuals.input_tokens`
2. `actuals.output_tokens`
3. `actuals.wall_time_sec`
4. `actuals.tool_calls`
5. `actuals.reopen_count`

Also include `done_gate` booleans, all set to `true`:

1. `done_gate.success_criteria_met`
2. `done_gate.safety_tests_passed`
3. `done_gate.implementation_tests_passed`
4. `done_gate.edge_case_tests_passed`
5. `done_gate.merged_to_main`
6. `done_gate.required_checks_passed_on_main`

These are used for rubric calibration, model predictor training, and completion quality controls.
