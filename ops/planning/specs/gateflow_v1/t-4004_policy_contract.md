# T-4004 Policy Contract (Protected Branch, Done Gate, Harness Warning Mode)

## Policy Scope

This contract freezes v1 policy behavior for:
1. `protected_branch`
2. `done_gate`
3. closeout harness warning mode

## `protected_branch` Contract

1. Branches matched by policy regex are immutable for direct task-state mutation commands.
2. State writes targeting protected branches must fail with explicit policy error (`exit=3`).
3. Allowed override path is explicit privileged mode flag with audit event.

## `done_gate` Contract

Task transition to `Done` requires:
1. `actuals.input_tokens >= 0`
2. `actuals.output_tokens >= 0`
3. `actuals.wall_time_sec >= 0`
4. `actuals.tool_calls >= 0`
5. `actuals.reopen_count >= 0`
6. all done-gate booleans present and `true`:
  - `success_criteria_met`
  - `safety_tests_passed`
  - `implementation_tests_passed`
  - `edge_case_tests_passed`
  - `merged_to_main`
  - `required_checks_passed_on_main`

## Closeout Harness Warning Mode

Modes:
1. `strict`: warnings escalate to failure.
2. `warn`: warnings emit but do not fail command.

Behavior:
1. Missing required evidence is always failure regardless of mode.
2. Optional provenance gaps are warnings in `warn`, failures in `strict`.
3. Mode is explicit in command output and machine-readable summary.

## Determinism Rules

1. Policy evaluation order: branch guard -> done gate -> harness checks.
2. Stable error ordering by policy id.
3. No hidden environment-dependent defaults.
