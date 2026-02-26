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

## Epic and Task Seed

### E-101 (M-001): Discord operations baseline completion
1. `T-101` Post artifact pack to mapped channels and pin baselines where allowed.
2. `T-102` Configure essential defaults for Carl-bot/sesh/MyRepoBot/Ticket Tool.
3. `T-103` Run rollout checker and publish pass report in `#iteration-reviews`.

### E-201 (M-002): App protocol docs finalization
1. `T-201` Add complete variant-routing examples to protocol docs.
2. `T-202` Add compatibility/deprecation matrix and migration notes.
3. `T-203` Add operator runbook examples and troubleshooting appendix.

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

## Initial Channel-to-Epic Placement
1. `#team-platform-ci-board`: E-101, E-401
2. `#team-protocol-board`: E-201
3. `#team-rendering-board`: E-301
4. `#team-security-quality-board`: E-501, E-601
5. `#team-runtime-board`: E-301 support tasks as needed
6. `#team-runtime-board`: E-701

## Weekly Review Checklist
1. Update each epic status and blockers.
2. Confirm milestone linkage remains valid.
3. Update confidence impact in `#milestones-gantt`.
4. Log decisions in `#adr-log` when major pivots occur.
