# F-011 Execution Board

Milestone: `F-011` App protocol docs finalized
Epic: `E-201`
Task chain: `T-201 -> T-202 -> T-203 -> T-204 -> T-205 -> T-206 -> T-207 -> T-208 -> T-209 -> T-210 -> T-211 -> T-212 -> T-213 -> T-214 -> T-215 -> T-216 -> T-217 -> T-218 -> T-219 -> T-2701 -> T-2702 -> T-2703`
Last updated: `2026-03-03`

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
17. `T-217` Implement first-party Planes runtime loader API (`load_plane_app`) for framework-managed parse/compile/render flow.
18. `T-218` Refactor `planes_v2_poc` to tiny `load_plane_app(...)` pattern with app-specific handlers only.
19. `T-219` Add Planes runtime tests/docs for dispatch behavior, viewport semantics, and PoC proof coverage.
20. `T-2701` Document incremental-present policy and invalidation semantics for current runtime behavior.
21. `T-2702` Document sensor fast-path/cached-path semantics and TTL/freshness behavior.
22. `T-2703` Publish compatibility and migration notes for performance-path changes with determinism guarantees.

Evidence:
1. `PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py tests/test_planes_protocol.py` (`40 passed`).
2. `PYTHONPATH=. uv run pytest tests/test_planes_v2_poc_example.py tests/test_planes_protocol.py tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py` (`42 passed`).
3. `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 5` (`run complete: ticks=5 frames=5 stopped_by_target_close=False stopped_by_energy_safety=False`).
4. `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` (`validation: PASS`).
5. `PYTHONPATH=. uv run pytest tests/test_planes_runtime.py tests/test_planes_v2_poc_example.py tests/test_planes_protocol.py tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py` (`45 passed`).
6. `PYTHONPATH=. uv run python main.py run-app examples/app_protocol/planes_v2_poc --render headless --ticks 10` (`run complete: ticks=10 frames=10 stopped_by_target_close=False stopped_by_energy_safety=False`).
7. `PYTHONPATH=. python3 -m pytest tests/test_display_runtime.py -k "revision_snapshot_flag or parity or coalesces_to_latest_revision" -q` (`3 passed`).
8. `PYTHONPATH=. python3 -m pytest tests/test_planes_runtime.py -k "incremental_present or invalidation_escape_hatch or scroll_visual_parity" -q` (`3 passed`).
9. `PYTHONPATH=. python3 -m pytest tests/test_sensor_manager.py tests/test_app_runtime.py -k "sensor" -q` (`8 passed`).
10. `PYTHONPATH=. python3 -m pytest tests/test_macos_vulkan_backend.py -k "persistent_map or transient_mode_maps_each_frame or upload_image_reuse or swapchain_invalidation" -q` (`5 passed`).

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
7. `2026-03-01`: Added protocol-v2 + Planes proof-of-concept app:
   - `examples/app_protocol/planes_v2_poc/app.toml` (`protocol_version = "2"`, runtime `python_inproc`)
   - `examples/app_protocol/planes_v2_poc/plane.json` (Planes schema payload)
   - `examples/app_protocol/planes_v2_poc/app_main.py` (tiny `load_plane_app(...)` entrypoint)
8. `2026-03-01`: Added proof test `tests/test_planes_v2_poc_example.py` and executed both test and runtime proof commands.
9. `2026-03-01`: Added first-party Planes runtime loader `luvatrix_ui/planes_runtime.py` and exported `load_plane_app` for app authors.
10. `2026-03-01`: Added runtime loader tests `tests/test_planes_runtime.py` (render mounting, handler dispatch, strict missing-handler failure).
11. `2026-03-01`: Updated task statuses via planning API: `T-217..T-219 -> Done`.
12. `2026-03-03`: Updated protocol docs for performance follow-up scope:
   - `docs/app_protocol.md` (incremental-present/invalidation and sensor cache semantics),
   - `docs/app_protocol_compatibility_policy.md` (performance-path compatibility contract),
   - `docs/app_protocol_v2_migration.md` (operator migration sequence and determinism checks).
13. `2026-03-03`: Applied GateFlow stage progression for `T-2701..T-2703` on `main` through `Integration Ready`, then `Done` with required `actuals` + `done_gate`.
14. `2026-03-03`: Verified follow-up behavior on `main` with targeted deterministic regression commands and planning-link validation pass.
