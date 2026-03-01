# GANTT: Historical + Active + Planned

Canonical schedule source: `discord/ops/milestone_schedule.json`.

## Milestone Legend
1. `Status`: Planned | In Progress | At Risk | Blocked | Complete
2. `Dependency`: upstream milestone IDs
3. `Historical`: grouped from merged commit history (main + integration branches)

## Historical Completed Milestones (Git-Derived)

1. `H-001` (2026-02-23)
- Title: Core package transition and repository cleanup
- Representative commits: `da0affc`, `b9cbb24`

2. `H-002` (2026-02-23)
- Title: macOS visual runtime foundation merged to main
- Representative commits: `aa10c8d` -> `de07329`

3. `H-003` (2026-02-24)
- Title: Runtime safety controller and audit pipeline hardening
- Representative commits: `31eebbf`, `9c4d0a1`

4. `H-004` (2026-02-26)
- Title: Platform variant routing and HDI phase standardization
- Representative commits: `4fecdf2`, `a5ae8d1`

5. `H-005` (2026-02-26)
- Title: Rendering fallback, smoke docs, and GPU blit path
- Representative commits: `87cf09c`, `4a805e7`, `fc9099a`

6. `H-006` (2026-02-26)
- Title: Interactive plot module and UI IR integration
- Representative commits: `8d966f5`, `0f8d9f3`, `3ef4e14`, `94f77f8`, `2af0337`, `9e1aa60`

7. `H-007` (2026-02-27)
- Title: Plot stabilization and stream simulation integration
- Representative commits: `8556c91`, `a3fc9ea`, `aca4a07`, `50675ea`

8. `H-008` (2026-02-26)
- Title: Discord ops consolidation under `/discord`
- Representative commit: `48c3c02`

9. `H-009` (2026-02-27)
- Title: Packaging metadata and Vulkan runtime preflight guidance
- Representative commits: `f255da9`, `5fdcad6`, `f943653`

## Active + Planned Roadmap Milestones

1. `M-001`
- Title: Discord governance artifacts and onboarding system
- Target window: Week 1-2
- Status: In Progress
- Dependencies: H-008
- Owner: CEO / Ops

2. `M-007`
- Title: Cross-platform full-suite interactive generalization
- Target window: Week 1-4
- Status: In Progress
- Dependencies: H-006, H-009
- Owner: Runtime/Platform

3. `M-002`
- Title: App protocol docs finalized (manifest variants, compatibility policy)
- Target window: Week 2-3
- Status: Planned
- Dependencies: M-001
- Owner: CEO / Protocol

4. `M-003`
- Title: Vulkan stabilization pass (surface/swapchain/fence resilience)
- Target window: Week 3-6
- Status: Planned
- Dependencies: M-002, M-007
- Owner: Runtime/Rendering

5. `M-004`
- Title: CI hardening with smoke observability and flaky governance
- Target window: Week 4-6
- Status: Planned
- Dependencies: M-002
- Owner: Platform/Quality

6. `M-005`
- Title: Audit retention/reporting lifecycle improvements
- Target window: Week 5-7
- Status: Planned
- Dependencies: M-004
- Owner: Core/Quality

7. `M-006`
- Title: Phase 1 production-hardening review and go/no-go
- Target window: Week 8-10
- Status: Planned
- Dependencies: M-003, M-004, M-005
- Owner: CEO + Leads

8. `M-008`
- Title: Plot + data UX foundations (sideways labels, bar chart, subplots, scrolling, table UI)
- Target window: Week 4-8
- Status: In Progress
- Dependencies: M-007
- Owner: Rendering + Runtime

9. `M-009`
- Title: Data workspace UI (calendar app)
- Target window: Week 8-9
- Status: Planned
- Dependencies: M-008
- Owner: Runtime + Protocol

10. `M-010`
- Title: Custom marketbook dynamic plotting system
- Target window: Week 9-12
- Status: Planned
- Dependencies: M-008, M-009
- Owner: Rendering + Runtime + Protocol

11. `M-011`
- Title: Native Gantt + Agile visualization in Luvatrix
- Target window: Week 10-13
- Status: In Progress
- Dependencies: M-008
- Owner: Rendering + Runtime + Platform/CI

## Branching and Merge Gate Policy
1. Each milestone is implemented first on its own milestone branch.
2. Cross-milestone dependencies are resolved either by upstream merge-to-`main` then pull, or direct source-branch pull/cherry-pick with traceable notes.
3. Milestone status may be `Implementation Complete` on branch, but milestone status is not `Complete` until merged to `main`.
4. `Complete` requires full functionality verification on `main` and required tests passing on `main`.

## Weekly Update Format
1. Milestone ID:
2. Planned vs actual progress:
3. New risks/blockers:
4. Dependency impact:
5. Branch integration status (`on-branch` / `integrated-to-main`):
6. Main-branch test status:
7. Next-week focus:
