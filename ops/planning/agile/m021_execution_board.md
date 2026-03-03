# P-021 Execution Board

Milestone: `P-021` Performance baseline and telemetry gates  
Epic: `E-2101`  
Task chain: `T-2101 -> T-2102 -> T-2103 -> T-2104`  
Last updated: `2026-03-03`

## Intake
1. None.

## Success Criteria Spec
1. `T-2101` Map exact per-frame copy chain with ownership boundaries.

## Safety Tests Spec
1. `T-2102` Verify copy counters/timers stay deterministic and non-negative.

## Implementation Tests Spec
1. `T-2103` Run deterministic scenario harness (`idle`, `scroll`, `drag`, `resize_stress`).

## Edge Case Tests Spec
1. `T-2104` Fail gate on deterministic replay mismatch or threshold regressions.

## Prototype Stage 1
1. `T-2101` copy-chain doc + instrumentation skeleton.
2. `T-2102` copy bytes/count and pack/map/memcpy timing hooks.
3. `T-2103` `tools/perf/run_suite.py` scenario harness.
4. `T-2104` `tools/perf/assert_thresholds.py` + baseline contract.

## Prototype Stage 2+
1. None.

## Verification Review
1. Evidence commands:
- `PYTHONPATH=. uv run pytest tests/test_app_runtime.py tests/test_display_runtime.py tests/test_planes_runtime.py tests/test_perf_tools.py`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario render_copy_chain --out artifacts/perf/render_copy_baseline.json`
- `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario all_interactive --out artifacts/perf/interactive_baseline.json`
- `PYTHONPATH=. uv run python tools/perf/assert_thresholds.py --suite baseline_contract --baseline artifacts/perf/interactive_baseline.json`

## Integration Ready
1. Pending verification on milestone branch.

## Done
1. None.

## Blocked
1. None.
