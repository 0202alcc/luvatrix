# M-002 Execution Board

Milestone: `M-002` App protocol docs finalized
Epic: `E-201`
Task chain: `T-201 -> T-202 -> T-203 -> T-204 -> T-205 -> T-206 -> T-207 -> T-208 -> T-209 -> T-210 -> T-211 -> T-212 -> T-213 -> T-214 -> T-215 -> T-216`
Last updated: `2026-03-01`

## Backlog
1. `T-205` Implement runtime adapter layer (python in-process baseline + process runtime hooks) for protocol v2 execution.
2. `T-206` Deliver Python-first protocol v2 process lane (stdio transport + reference worker SDK/client) while keeping v1 behavior unchanged.
3. `T-207` Extend app manifest/governance for v2 runtime fields with strict compatibility policy and v1-safe defaults.
4. `T-208` Add protocol v1/v2 conformance matrix and CI gates for adapter/runtime compatibility and deterministic render outputs.
5. `T-209` Publish v1-to-v2 migration guide and runbook updates for first-party app teams (Python-first, multi-language ready).
6. `T-211` Standardize Planes interaction hooks against HDI-normalized phases and event payload contracts.
7. `T-212` Define Planes script registry and deterministic function target resolution (`<script_id>::<function_name>`) with strict-mode failures.
8. `T-213` Specify Planes viewport clipping and scroll-window semantics (coordinate remap, bounds, deterministic pan behavior).
9. `T-214` Define Planes Gantt+Agile feature profile and status-theming contract for first-party planning app templates.
10. `T-215` Implement deterministic compiler mapping from Planes JSON to shared UI IR (draw/hit-test ordering + frame transforms).
11. `T-216` Add Planes strict/permissive schema validation and conformance tests (including v1/v2 protocol integration gates).

## Ready
1. `T-204` Define App Protocol v2 superset wire spec with v1 backward-compatibility guarantees.
2. `T-210` Finalize Planes Protocol v0 core schema (app/plane/component contracts, metadata inheritance, unit normalization).

## In Progress
1. None.

## Review
1. None.

## Done
1. `T-201` Add complete variant-routing examples to protocol docs.
- Evidence:
  `PYTHONPATH=. uv run pytest tests/test_app_runtime.py tests/test_protocol_governance.py tests/test_unified_runtime.py` (pass, 29 tests)
2. `T-202` Add compatibility/deprecation matrix and migration notes.
- Evidence:
  `PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py` (covered by suite above, pass)
3. `T-203` Add operator runbook examples and troubleshooting appendix.
- Evidence:
  `PYTHONPATH=. uv run pytest tests/test_unified_runtime.py tests/test_app_runtime.py` (covered by suite above, pass)

## Evidence Log
1. `2026-03-01`: Added `docs/app_protocol_variants_guide.md` with variant precedence, manifest snippets, run commands, unsupported-platform and bad-module-root failure cases.
2. `2026-03-01`: Added `docs/app_protocol_compatibility_policy.md` with protocol matrix, bounds behavior, deprecation lifecycle, and migration checklist/examples.
3. `2026-03-01`: Added `docs/app_protocol_operator_runbook.md` with operator cookbook, troubleshooting tree, incidents/recovery, and audit verification steps.
4. `2026-03-01`: Linked new protocol docs from `docs/app_protocol.md` and `README.md`.
5. `2026-03-01`: Updated task statuses via planning API:
   `T-201/T-202/T-203 -> Done`, `M-002 -> In Progress`.
6. `2026-03-01`: Validation and regression verification passed:
   `PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py` (`29 passed`).
7. `2026-03-01`: Added phase-2 `M-002` tickets through planning API with milestone + team + specialist board refs:
   `T-204` (Ready), `T-205..T-209` (Backlog).
8. `2026-03-01`: Added dependency chain for backward-compatible v2 rollout:
   `T-204 -> T-205 -> T-206` and `T-204 -> T-207 -> T-208 -> T-209`, with `T-208` also depending on `T-205` and `T-206`.
9. `2026-03-01`: Added Planes protocol formal spec:
   `docs/planes_protocol_v0.md` (metadata inheritance, HDI hook contract, scripts/function resolution, viewport semantics, Gantt/Agile profile).
10. `2026-03-01`: Added phase-3 Planes tickets through planning API:
   `T-210` (Ready), `T-211..T-216` (Backlog) with cross-team board refs for protocol/runtime/rendering/CI/security coverage.
11. `2026-03-01`: Added Planes dependency chain:
   `T-210 -> {T-211,T-212,T-213}`, `T-210+T-213 -> T-214`, `{T-211,T-212,T-213,T-214} -> T-215 -> T-216`.
