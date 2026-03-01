# Agile Board Seed (Milestone-Linked)

Use this to initialize all `02_TEAM_AGILE_BOARDS` channels with executable items.

## Board Workflow
1. `Backlog`
2. `Ready`
3. `In Progress`
4. `Review`
5. `Done`

Every card must include:
1. `Epic ID` (`E-###`)
2. `Task ID` (`T-###`)
3. `Milestone` (`M-###`)
4. Owner
5. Test evidence links before moving to `Done`

## Milestone Branching + Completion Gate
1. Each milestone executes on its own milestone branch first.
2. If tasks require upstream milestone changes, resolve via upstream-to-`main` merge, then pull `main`; or direct pull/cherry-pick from source milestone branch with traceable notes.
3. Milestone status is `Implementation Complete` when branch work is functionally done.
4. Milestone status moves to `Complete` only when all milestone changes are merged to `main`.
5. Full milestone functionality must be verified on `main`.
6. Required tests must pass on `main` integration.

## Epic and Task Seed

### E-101 (M-001): Discord operations baseline completion
1. `T-101` Post artifact pack to mapped channels and pin baselines where allowed.
2. `T-102` Configure essential defaults for Carl-bot/sesh/MyRepoBot/Ticket Tool.
3. `T-103` Run rollout checker and publish pass report in `#iteration-reviews`.

### E-201 (M-002): App protocol docs finalization
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

### E-701 (M-007): Full-suite interactive cross-platform generalization
1. `T-701` Add platform-aware runtime path: macOS windowed + non-macOS headless.
2. `T-702` Keep animation/frame behavior identical across platform paths.
3. `T-703` Add non-macOS system telemetry providers and unavailable fallbacks.
4. `T-704` Update tests/docs and validate no regression in dashboard formatting.

### E-301 (M-003): Vulkan stabilization
1. `T-301` Collect and classify top swapchain/surface/fence failure modes.
2. `T-302` Add targeted regression tests for each failure class.
3. `T-303` Implement resiliency fixes and fallback parity checks.
4. `T-304` Run stability soak and publish defect burn-down.

### E-401 (M-004): CI hardening
1. `T-401` Define deterministic gate ownership and required pass criteria.
2. `T-402` Add flaky test quarantine + remediation workflow.
3. `T-403` Improve smoke signal visibility and artifact links.

### E-501 (M-005): Audit retention lifecycle
1. `T-501` Define retention policy defaults and rationale.
2. `T-502` Validate prune/report workflows under realistic load.
3. `T-503` Publish operational playbook for retention management.

### E-601 (M-006): Production-hardening review
1. `T-601` Assemble milestone completion evidence packet.
2. `T-602` Review unresolved risks/defects and required mitigations.
3. `T-603` Publish go/no-go recommendation with rationale and decision log links.

### E-801 (M-008): Plot UX foundations
1. `T-801` Sideways x-axis rule labels for long names with readable wrapping/fallbacks.
2. `T-802` Bar chart renderer support (static + interactive parity).
3. `T-803` Multiple plot support (subplot-like layout orchestration).
4. `T-804` Scrolling and viewport controls for dense plot surfaces.
5. `T-805` Table UI component system (sortable columns, pagination/virtualization, keyboard access).
6. Dependency order: `T-801 -> T-802 -> T-803 -> T-804 -> T-805`.

### E-901 (M-009): Data workspace UI
1. `T-901` Calendar app component (day/week/month views + event rendering contract).
2. `T-902` Calendar workflow integration with data workspace navigation/state sync.
3. Dependency order: `T-901 -> T-902`.

### E-1001 (M-010): Marketbook plotting system
1. `T-1001` Marketbook schema + ingestion adapter contract.
2. `T-1002` Dedicated dynamic marketbook renderer (depth ladder, spread, imbalance traces).
3. `T-1003` Streaming update strategy + latency/perf budgets.
4. `T-1004` Regression/safety tests and operator docs.
5. Dependency order: `T-1001 -> T-1002 -> T-1003 -> T-1004`.

### E-1101 (M-011): Native Gantt + Agile visualization
1. `T-1101` Define canonical timeline/task schema for Gantt + Agile cards (milestones, tasks, status, deps, owners).
2. `T-1102` Build Luvatrix Gantt renderer (time axis, status colors, dependency lines, collapsed/expanded lanes).
3. `T-1103` Build Luvatrix Agile board renderer (Backlog/Ready/In Progress/Review/Done, swimlanes, blockers).
4. `T-1104` Add interaction layer (filtering, zoom/scroll, click-through from milestone -> task cards).
5. `T-1105` Add export adapters (ASCII/Markdown/PNG) and Discord posting payload compatibility.
6. `T-1106` Add validation suite (render correctness, dependency integrity, snapshot/regression tests).
7. Dependency order: `T-1101 -> T-1102 -> T-1103 -> T-1104 -> T-1105 -> T-1106`.
8. Mandatory success criteria: all `M-011` deliverables must follow first-party Luvatrix App Protocol contracts and remain first-party module driven (no external UI runtime coupling).
9. Acceptance gate: do not move any `T-110#` to `Done` without evidence that schema/renderer/interaction/export/validation behavior is deterministic and App Protocol-compliant.
10. Scope note: `M-011` does not require standalone data-table UX; it depends on timeline/board visualization primitives and shared viewport interactions.

## Master Ordered Execution Chain (As Requested)
1. `T-801` Sideways x labels
2. `T-802` Bar chart
3. `T-803` Multiple plot support
4. `T-804` Scrolling
5. `T-805` Table UI
6. `T-901` Calendar app
7. `T-902` Calendar workspace integration
8. `T-1001` Marketbook schema/ingestion
9. `T-1002` Marketbook dynamic renderer
10. `T-1003` Streaming/perf budgets
11. `T-1004` Safety/regression/docs closeout
12. `T-1101` Gantt/Agile schema contract
13. `T-1102` Gantt renderer
14. `T-1103` Agile board renderer
15. `T-1104` Interaction layer
16. `T-1105` Export + Discord adapters
17. `T-1106` Validation suite + release gate

## Initial Channel-to-Epic Placement
1. `#team-platform-ci-board`: E-101, E-401
2. `#team-protocol-board`: E-201
3. `#team-rendering-board`: E-301
4. `#team-security-quality-board`: E-501, E-601
5. `#team-runtime-board`: E-301 support tasks as needed
6. `#team-runtime-board`: E-701
7. `#team-rendering-board`: E-801, E-1001
8. `#team-runtime-board`: E-901 support tasks
9. `#team-protocol-board`: E-1001 schema/contracts
10. `#team-rendering-board`: E-1101 renderer tasks
11. `#team-runtime-board`: E-1101 interaction/export tasks
12. `#team-platform-ci-board`: E-1101 validation + release gates

## Deliberation Queue Channel (Planned)
1. Channel name recommendation: `#feature-deliberation-lab`.
2. Purpose: CEO + AI experts convert idea proposals into milestone IDs and task cards before backlog intake.
3. Intake template:
1. Feature title:
2. Why now:
3. Success criteria:
4. Safety risks/tests:
5. Dependencies:
6. Proposed milestone/epic/task IDs:
7. Owner candidates:
8. Decision outcome:

## Weekly Review Checklist
1. Update each epic status and blockers.
2. Confirm milestone linkage remains valid.
3. Update confidence impact in `#milestones-gantt`.
4. Log decisions in `#adr-log` when major pivots occur.
