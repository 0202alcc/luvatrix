# M-002 Execution Board

Milestone: `M-002` App protocol docs finalized
Epic: `E-201`
Task chain: `T-201 -> T-202 -> T-203 -> T-204 -> T-205 -> T-206 -> T-207 -> T-208 -> T-209 -> T-210 -> T-211 -> T-212 -> T-213 -> T-214 -> T-215 -> T-216`
Last updated: `2026-03-01`

## Backlog
1. None.

## Ready
1. None.

## In Progress
1. None.

## Review
1. None.

## Done
1. `T-201` Add complete variant-routing examples to protocol docs.
2. `T-202` Add compatibility/deprecation matrix and migration notes.
3. `T-203` Add operator runbook examples and troubleshooting appendix.
4. `T-204` Define App Protocol v2 superset wire spec with v1 backward-compatibility guarantees.
5. `T-205` Implement runtime adapter layer (python in-process baseline + process runtime hooks) for protocol v2 execution.
6. `T-206` Deliver Python-first protocol v2 process lane (stdio transport + reference worker SDK/client) while keeping v1 behavior unchanged.
7. `T-207` Extend app manifest/governance for v2 runtime fields with strict compatibility policy and v1-safe defaults.
8. `T-208` Add protocol v1/v2 conformance matrix and CI gates for adapter/runtime compatibility and deterministic render outputs.
9. `T-209` Publish v1-to-v2 migration guide and runbook updates for first-party app teams (Python-first, multi-language ready).
10. `T-210` Finalize Planes Protocol v0 core schema (app/plane/component contracts, metadata inheritance, unit normalization).
11. `T-211` Standardize Planes interaction hooks against HDI-normalized phases and event payload contracts.
12. `T-212` Define Planes script registry and deterministic function target resolution (`<script_id>::<function_name>`) with strict-mode failures.
13. `T-213` Specify Planes viewport clipping and scroll-window semantics (coordinate remap, bounds, deterministic pan behavior).
14. `T-214` Define Planes Gantt+Agile feature profile and status-theming contract for first-party planning app templates.
15. `T-215` Implement deterministic compiler mapping from Planes JSON to shared UI IR (draw/hit-test ordering + frame transforms).
16. `T-216` Add Planes strict/permissive schema validation and conformance tests (including v1/v2 protocol integration gates).

Evidence:
1. `PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py tests/test_planes_protocol.py` (`40 passed`).
2. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` (`validation: PASS`).

## Evidence Log
1. `2026-03-01`: Added formal Planes spec: `docs/planes_protocol_v0.md`.
2. `2026-03-01`: Added protocol-v2 documents:
   - `docs/app_protocol_v2_superset_spec.md`
   - `docs/app_protocol_v2_conformance_matrix.md`
   - `docs/app_protocol_v2_migration.md`
3. `2026-03-01`: Implemented runtime v2 compatibility path:
   - manifest runtime table parsing (`kind`, `transport`, `command`),
   - process runtime lifecycle bridge over `stdio_jsonl`,
   - Python process worker SDK.
4. `2026-03-01`: Implemented Planes validation + compiler mapping to shared UI IR, including HDI hook validation, script target resolution, unit normalization, and viewport contract checks.
5. `2026-03-01`: Added conformance tests for protocol governance/runtime/process lane and Planes compiler/validation.
6. `2026-03-01`: Updated task statuses via planning API: `T-204..T-216 -> Done`.
