# GANTT: Milestone Timeline Baseline

## Milestone Legend
1. `Status`: Planned | In Progress | At Risk | Blocked | Complete
2. `Confidence`: High | Medium | Low
3. `Dependency`: upstream milestone IDs

## Milestones

1. `M-001`
- Title: Discord operating system baseline live (channels, governance, bots, artifacts)
- Target window: Week 1
- Status: In Progress
- Confidence: Medium
- Dependencies: None
- Owner: CEO

2. `M-002`
- Title: App protocol docs finalized (manifest variants, compatibility policy)
- Target window: Week 2-3
- Status: Planned
- Confidence: Medium
- Dependencies: M-001
- Owner: CEO

3. `M-003`
- Title: Vulkan stabilization pass (surface/swapchain/fence resilience)
- Target window: Week 3-6
- Status: Planned
- Confidence: Medium
- Dependencies: M-002
- Owner: Runtime/Rendering

4. `M-004`
- Title: CI hardening with smoke observability and flaky governance
- Target window: Week 4-6
- Status: Planned
- Confidence: Medium
- Dependencies: M-002
- Owner: Platform/Quality

5. `M-005`
- Title: Audit retention/reporting lifecycle improvements
- Target window: Week 5-7
- Status: Planned
- Confidence: Medium
- Dependencies: M-004
- Owner: Core/Quality

6. `M-006`
- Title: Phase 1 production-hardening review and go/no-go
- Target window: Week 8-10
- Status: Planned
- Confidence: Low
- Dependencies: M-003, M-004, M-005
- Owner: CEO + Leads

7. `M-007`
- Title: Cross-platform full-suite interactive generalization
- Target window: Week 2-4
- Status: In Progress
- Confidence: Medium
- Dependencies: M-001
- Owner: Runtime/Platform

## Weekly Update Format
1. Milestone ID:
2. Planned vs actual progress:
3. New risks/blockers:
4. Confidence change and reason:
5. Next-week focus:
