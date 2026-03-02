# UI IR v2 Rollout and Compatibility Gate Plan (T-825)

Status: Draft plan (2026-03-01)
Milestone: M-008
Task: T-825

## 1) Purpose

Define the release gate policy for introducing `planes-v2` behavior while protecting `planes-v0` compatibility and deterministic runtime guarantees.

## 2) Rollout Principles

1. Default-safe: `planes-v0` behavior remains stable until all gates pass.
2. Deterministic-first: no rollout if ordering/compositing determinism is uncertain.
3. Observable rollout: every phase requires explicit metrics and pass/fail records.
4. Reversible rollout: each phase has a documented rollback switch.

## 3) Compatibility Gate Matrix

Gate G1. Schema/IR validation
1. T-820 matrix scenarios `S01..S18` pass.
2. Strict and permissive mode expected outcomes match spec.

Gate G2. Runtime correctness
1. section-cut routing semantics pass.
2. blend clamp tests pass.
3. scroll/camera semantics pass for page-level and viewport-level paths.

Gate G3. Backward compatibility
1. Legacy `planes-v0` test suite remains green.
2. v0 payloads run without schema migration requirement.
3. Optional v0->v2 compatibility-lift mode produces deterministic IR.

Gate G4. Determinism stability
1. Snapshot/hash parity across repeated runs.
2. No nondeterministic ordering in diagnostics or render output.

Gate G5. Performance readiness
1. Required telemetry available.
2. p95 compose-time target met for representative fixtures.
3. No correctness drift between optimized and baseline paths.

## 4) Rollout Phases

Phase R0. Spec-only and dormant
1. Docs complete.
2. Runtime defaults unchanged.

Phase R1. Opt-in compile/runtime flags
1. Enable `planes-v2` only behind explicit capability flags.
2. Collect telemetry and failure diagnostics.

Phase R2. Controlled adoption
1. Enable `planes-v2` by default for selected internal fixtures/apps.
2. Keep quick rollback flag enabled.

Phase R3. Default-on
1. Flip default to `planes-v2` once all gates are stable for defined soak period.
2. Keep `planes-v0` compatibility path during deprecation window.

Phase R4. Deprecation execution
1. Announce `planes-v0` deprecation timeline.
2. Remove dormant code only after policy window and migration completion.

## 5) Rollback Plan

1. Runtime rollback switch:
- force `planes-v0` compile path.

2. Feature rollback switch:
- disable culling/cache/prefetch independently if instability appears.

3. Incident rollback trigger examples:
- deterministic snapshot drift,
- hard runtime exceptions in supported fixtures,
- compatibility regression against v0 contracts.

## 6) Required CI Gates

Required command set:
```bash
PYTHONPATH=. uv run pytest tests/test_planes_protocol.py tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py
```

Optional extended set:
```bash
PYTHONPATH=. uv run pytest tests/test_luvatrix_plot.py tests/test_luvatrix_ui_table.py tests/test_plot_app_protocol_example.py
```

Headless smoke:
```bash
PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 16 --fps 60
```

## 7) Release Readiness Checklist

1. T-820 through T-824 artifacts approved.
2. All gate commands pass in CI.
3. Rollback switches validated in staging.
4. Release notes include capability flags and migration notes.
5. Board status moved to `Done` only after acceptance + evidence links.

## 8) Ownership and Audit Trail

1. Gate outcome records added to board evidence log.
2. Each phase transition requires:
- commit reference,
- test evidence,
- reviewer acknowledgment.

## 9) Implementation Boundary

Planning-only task. No runtime code changes in this step.

## 10) Evidence

1. `docs/ui_ir_v2_validation_plan.md`
2. `docs/ui_ir_v2_compiler_upgrade_design.md`
3. `docs/ui_ir_v2_runtime_pipeline_design.md`
4. `docs/ui_ir_v2_performance_execution_plan.md`
5. `docs/ui_ir_v2_demo_verification_plan.md`
6. `ops/planning/agile/m008_execution_board.md`
