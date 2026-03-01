# Agile Lineage and Milestone Boards (Deep Trace)

As-of date: 2026-02-28.

## 1) Improved Wide ASCII Gantt (Historical + Current Plan)

Baseline week start is 2026-02-23.

```text
Week:   W01          W02          W03          W04          W05          W06          W07          W08          W09          W10
Date:   02/23-03/01  03/02-03/08  03/09-03/15  03/16-03/22  03/23-03/29  03/30-04/05  04/06-04/12  04/13-04/19  04/20-04/26  04/27-05/03

H-001 🧬 Core Package Transition                       |██████████                                                                                              | Status=Complete (2026-02-23)
H-002 🖥️ macOS Visual Runtime Foundation               |██████████                                                                                              | Status=Complete (2026-02-23)
H-003 ⚡ Runtime Safety + Audit Hardening              |██████████                                                                                              | Status=Complete (2026-02-24)
H-004 🧭 Variant Routing + HDI Standardization         |██████████                                                                                              | Status=Complete (2026-02-26)
H-005 🎯 Rendering Fallback + GPU Blit                 |██████████                                                                                              | Status=Complete (2026-02-26)
H-006 📈 Plot Module + UI IR Integration               |██████████                                                                                              | Status=Complete (2026-02-26)
H-007 🔌 Plot Stabilization + Stream Simulation        |██████████                                                                                              | Status=Complete (2026-02-27)
H-008 🗂️ Discord Ops Consolidation                     |██████████                                                                                              | Status=Complete (2026-02-26)
H-009 📦 Packaging + Vulkan Preflight Guidance         |██████████                                                                                              | Status=Complete (2026-02-27)
M-001 🧱 Discord Governance + Onboarding               |████████████████████                                                                                    | Status=In Progress
M-002 📜 App Protocol Docs Finalized                   |          ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                                                                            | Status=Planned
M-003 🎮 Vulkan Stabilization                          |                    ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                                                | Status=Planned
M-004 🧪 CI Hardening + Flaky Governance               |                              ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                                                    | Status=Planned
M-005 🛡️ Audit Retention Lifecycle                     |                                        ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                                          | Status=Planned
M-006 🚀 Production-Hardening Go/No-Go                 |                                                                      ▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒            | Status=Planned
M-007 🌐 Cross-Platform Interactive Generalization     |██████████▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒▒                                                                    | Status=In Progress

Legend: █ completed/active occupancy, ▒ planned occupancy.
```

Accuracy checks:
1. Historical milestones `H-001..H-009` are grouped directly from commit history and marked complete with explicit dates.
2. `M-007` is currently active and begins in W01.
3. Planned milestones remain W02+ while active streams overlap as expected in hybrid execution.

## 2) Exact Branch Integration Provenance (Commit Topology)

Confidence key:
1. `HIGH`: merge parent proves source branch lineage.
2. `MEDIUM`: inferred from side-chain merges where branch label not preserved.
3. `DIRECT`: committed on `main` first-parent (no side-branch provenance needed).

### Provenance Records

1. `aa10c8d` macOS visual runtime baseline
- Source branch: `codex/3b16aa823553-on-the-web-interface-i-want-to-simplify-`
- Integration commit: `de07329` (`parent2=aa10c8d`)
- Confidence: HIGH

2. `8556c91` dynamic 2D rolling fix
- Source branch: `codex/plot-module-v0`
- Integration commit: `aca4a07` (`parent2=8556c91`)
- Confidence: HIGH

3. `a3fc9ea` fake websocket stream + live buffer API
- Source branch: `codex/plot-module-v0`
- Integration commit: `50675ea` (`parent2=a3fc9ea`)
- Confidence: HIGH

4. `8d966f5`, `0f8d9f3`, `3ef4e14`, `94f77f8`, `2af0337`, `9e1aa60`
- Source branch: `main` first-parent
- Integration: direct (no merge needed)
- Confidence: DIRECT

5. `31eebbf`, `9c4d0a1`, `4fecdf2`, `a5ae8d1`, `48c3c02`, `87cf09c`, `4a805e7`, `fc9099a`, `f255da9`, `5fdcad6`, `f943653`
- Source branch: `main` first-parent
- Integration: direct
- Confidence: DIRECT

6. `e79a543`, `c4a9d6b`, `efdf22d`, `a2d43f4`, `300eb2c`, `23fdf2a`
- Source branch: side integration line prior to final `main` merge; branch label not explicit
- Integration: through chain ending in `aca4a07`/`50675ea`
- Confidence: MEDIUM

## 3) Ordinal Team Flow by Branch

This represents the metaphorical team handoff order per branch.

```text
Branch: codex/3b16...
  (1) Rendering/Core Specialist -> (2) Integration Specialist -> (3) Runtime Hardening Specialist on main
  Commits: aa10c8d -> de07329 -> 31eebbf/9c4d0a1/4fecdf2

Branch: codex/plot-module-v0
  (1) Plot Specialist -> (2) Fix/Quality Specialist -> (3) Integration Specialist -> (4) Release Specialist
  Commits: 8556c91, a3fc9ea -> aca4a07, 50675ea -> f255da9, 5fdcad6

Branch: codex/ui-ir-protocol
  (1) Mirror/Coordination Specialist only (sync branch; no unique origin commit currently)
  Commits: 8c5d739 -> 67af771

Branch: codex/rendering
  (1) Mirror/Coordination Specialist only (sync branch; no unique origin commit currently)
  Commits: f017008 -> 34741af

Branch: codex/discord-ops-foundation
  (1) Mirror/Coordination Specialist only (sync branch; feature commit already landed on main)
  Commits: 7d8d0f9 -> ece4516
```

## 4) World-Class Iterative Software Development Workflow (Mostly-AI Team)

Roles:
1. `PM` (Project Manager / Orchestrator)
2. `ARCH` (System Architect)
3. `TEST` (Verification Engineer)
4. `SAFE` (Safety & Risk Engineer)
5. `DEV` (Implementation Engineer)
6. `INTG` (Integration/CI Engineer)
7. `QA` (Quality/Performance Engineer)
8. `REL` (Release Engineer)
9. `OBS` (Observability Engineer)
10. `DOC` (Documentation Engineer)

Canonical ordered flow per milestone:
1. `PM` defines success criteria, constraints, and acceptance tests.
2. `ARCH` drafts technical design and decomposition.
3. `TEST` drafts proof tests against success criteria.
4. `SAFE` reviews architecture and adds safety tests + hazard controls.
5. `DEV` implements design slices.
6. `INTG` validates integration in CI and resolves environment issues.
7. `QA` executes regression/performance/non-functional gates.
8. `PM + ARCH + TEST + SAFE` perform prototype acceptance review.
9. `REL` performs release/handoff decision package.
10. `OBS + DOC` publish runbook, telemetry hooks, and post-release checks.

Unlock rules:
1. A task is unlocked only when prerequisite tasks are `Done`.
2. A task may be handled by any designated handler if primary is occupied.
3. Blocked tasks must include blocker ID and owner.

## 5) Milestone ASCII Agile Boards (Tasks, Handlers, Unlocks)

Handler pools:
1. `PM`: `{CEO, AI-PM}`
2. `ARCH`: `{AI-Architect, AI-Runtime, AI-Rendering}`
3. `TEST`: `{AI-TestEngineer, AI-Protocol}`
4. `SAFE`: `{AI-Safety, AI-TestEngineer}`
5. `DEV-RUNTIME`: `{AI-Runtime, AI-Implementer}`
6. `DEV-RENDER`: `{AI-Rendering, AI-Implementer}`
7. `DEV-PLATFORM`: `{AI-CI, AI-Implementer}`
8. `INTG`: `{AI-CI, AI-ReleaseReviewer}`
9. `QA`: `{AI-TestEngineer, AI-ReleaseReviewer}`
10. `REL`: `{CEO, AI-ReleaseReviewer}`
11. `DOC`: `{AI-PM, AI-Docs}`

### H-001 Core Package Transition and Repository Cleanup (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H1-S01 [PM] Define rename/sunset success criteria
                                                - Goal: replace legacy core identity, remove obsolete web prototype, keep runnable baseline.
                                              H1-S02 [ARCH] Define target package topology (`luvatrix_core/*`) and entrypoint contract
                                                - U: H1-S01
                                              H1-S03 [TEST] Define migration acceptance checks (import + run + docs path checks)
                                                - U: H1-S01
                                              H1-S04 [DEV-RUNTIME] Implement package rename/migration and baseline module scaffolding
                                                - U: H1-S02,H1-S03
                                              H1-S05 [DEV-RUNTIME] Rehome demo artifacts and page config to current structure
                                                - U: H1-S04
                                              H1-S06 [DOC] Update README/pyproject/planning references to new package identity
                                                - U: H1-S04
                                              H1-S07 [SAFE,TEST] Verify legacy-web removal safety (no broken required runtime paths)
                                                - U: H1-S05,H1-S06
                                              H1-S08 [DEV-PLATFORM] Remove redundant `luvatrix-core` symlink and cleanup repo pointers
                                                - U: H1-S07
                                              H1-S09 [INTG,QA] Final repo smoke/integration checks after cleanup
                                                - U: H1-S08
                                              H1-S10 [REL] Milestone closeout record + commit evidence publication
                                                - U: H1-S09
```

H-001 execution evidence:
1. Commit `da0affc` -> implements H1-S01..H1-S07 (rename, structure, docs, baseline artifacts).
2. Commit `b9cbb24` -> implements H1-S08..H1-S10 closeout cleanup (redundant symlink removal + final docs touch).
3. Branch provenance: `main` direct integration (no side branch merge).

### H-002 macOS Visual Runtime Foundation (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H2-S01 [PM] Define visual runtime baseline criteria (windowing, Vulkan compatibility, testability)
                                              H2-S02 [ARCH] Specify platform abstraction (`platform/*`, `targets/*`) and runtime contract
                                                - U: H2-S01
                                              H2-S03 [TEST] Define runtime/presenter/backend test matrix and acceptance thresholds
                                                - U: H2-S01
                                              H2-S04 [DEV-RUNTIME] Implement display runtime + window matrix core behavior
                                                - U: H2-S02,H2-S03
                                              H2-S05 [DEV-RENDER] Implement macOS Vulkan backend/presenter/window system components
                                                - U: H2-S04
                                              H2-S06 [ARCH,DEV-RENDER] Add shared Vulkan compatibility layer and target abstraction
                                                - U: H2-S05
                                              H2-S07 [DEV-RUNTIME,DOC] Add visualizer examples (`preserve_aspect`, `stretch`, probe utility)
                                                - U: H2-S06
                                              H2-S08 [TEST,SAFE] Add and validate runtime/frame-pipeline/backend/presenter protocol tests
                                                - U: H2-S07
                                              H2-S09 [INTG,DOC] Update package/runtime docs and dependency locks
                                                - U: H2-S08
                                              H2-S10 [REL] Merge and record milestone completion evidence
                                                - U: H2-S09
```

H-002 execution evidence:
1. Commit `aa10c8d` -> implements H2-S01..H2-S09 (runtime foundation, platform split, examples, tests).
2. Commit `de07329` -> implements H2-S10 (merge integration from `codex/3b16aa...` into `main`).
3. Branch provenance: `codex/3b16aa823553-on-the-web-interface-i-want-to-simplify-` -> `main`.

### H-003 Runtime Safety Controller and Audit Pipeline Hardening (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H3-S01 [PM] Define runtime safety/governance success criteria and audit obligations
                                              H3-S02 [ARCH] Design unified runtime interfaces for app runtime, HDI thread, sensors, audit sink
                                                - U: H3-S01
                                              H3-S03 [TEST] Define protocol-governance and sensor-runtime verification suite
                                                - U: H3-S01
                                              H3-S04 [DEV-RUNTIME] Implement app runtime + unified runtime + governance/audit modules
                                                - U: H3-S02,H3-S03
                                              H3-S05 [DEV-RUNTIME] Implement macOS HDI/sensor sources and integration hooks
                                                - U: H3-S04
                                              H3-S06 [DEV-RUNTIME,SAFE] Add runtime energy safety controller and policy hooks
                                                - U: H3-S05
                                              H3-S07 [DOC] Publish app protocol/runtime docs and runnable sensor logger examples
                                                - U: H3-S06
                                              H3-S08 [INTG,TEST] Add CI smoke workflow and expand unit/integration tests
                                                - U: H3-S07
                                              H3-S09 [QA] Validate end-to-end runtime behavior, audit trail, and safety fallback behavior
                                                - U: H3-S08
                                              H3-S10 [REL] Close milestone with evidence bundle
                                                - U: H3-S09
```

H-003 execution evidence:
1. Commit `31eebbf` -> implements H3-S01..H3-S05,H3-S07,H3-S08 (runtime/governance/audit/sensors + docs/examples/tests/CI).
2. Commit `9c4d0a1` -> implements H3-S06,H3-S09,H3-S10 (energy safety integration + final validation path).
3. Branch provenance: `main` direct integration.

### H-004 Platform Variant Routing and HDI Phase Standardization (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H4-S01 [PM] Define cross-platform variant-routing criteria and HDI phase consistency goals
                                              H4-S02 [ARCH] Define variant routing model and HDI phase contract across runtime boundaries
                                                - U: H4-S01
                                              H4-S03 [TEST] Define route/phase regression tests and coordinate-frame invariants
                                                - U: H4-S01
                                              H4-S04 [DEV-RUNTIME] Implement platform variant routing in app runtime
                                                - U: H4-S02,H4-S03
                                              H4-S05 [DEV-RUNTIME] Standardize HDI phases in thread/source/sensor pipeline
                                                - U: H4-S04
                                              H4-S06 [DEV-RUNTIME,ARCH] Add dynamic coordinate frame support for full-suite flows
                                                - U: H4-S05
                                              H4-S07 [DOC] Refresh protocol docs, examples, and planning artifacts for new routing semantics
                                                - U: H4-S06
                                              H4-S08 [TEST,INTG] Expand runtime/hdi/sensor/coordinate tests and run integration validation
                                                - U: H4-S07
                                              H4-S09 [REL] Approve and close milestone
                                                - U: H4-S08
```

H-004 execution evidence:
1. Commit `4fecdf2` -> implements H4-S01..H4-S04 (variant routing + plan/docs/test updates).
2. Commit `a5ae8d1` -> implements H4-S05..H4-S09 (HDI phase standardization + coordinates + full-suite examples + test expansion).
3. Branch provenance: `main` direct integration.

### H-005 Rendering Fallback, Smoke Docs, and GPU Blit Path (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H5-S01 [PM] Define rendering resiliency/performance acceptance criteria for macOS fallback path
                                              H5-S02 [ARCH] Define fallback-vs-GPU-blit behavior and scaling policy expectations
                                                - U: H5-S01
                                              H5-S03 [TEST] Define fallback correctness and blit regression test cases
                                                - U: H5-S01
                                              H5-S04 [DEV-RENDER] Restore clean fallback rendering behavior
                                                - U: H5-S02,H5-S03
                                              H5-S05 [DOC] Publish fallback smoke-test procedure for operators
                                                - U: H5-S04
                                              H5-S06 [DEV-RENDER] Add GPU blit scaling path and integrate with backend runtime
                                                - U: H5-S05
                                              H5-S07 [TEST,QA] Validate fallback and GPU blit paths under regression conditions
                                                - U: H5-S06
                                              H5-S08 [REL] Close milestone with performance/risk notes
                                                - U: H5-S07
```

H-005 execution evidence:
1. Commit `87cf09c` -> implements H5-S04 (fallback restore).
2. Commit `4a805e7` -> implements H5-S05 (fallback smoke doc + cleanup refinement).
3. Commit `fc9099a` -> implements H5-S06..H5-S08 (GPU blit path + tests + completion).
4. Branch provenance: `main` direct integration.

### H-006 Interactive Plot Module and UI IR Integration (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H6-S01 [PM] Define interactive plotting + UI-IR integration success criteria
                                              H6-S02 [ARCH] Define plot API/compiler/raster architecture and runtime renderer interfaces
                                                - U: H6-S01
                                              H6-S03 [TEST] Define core plotting correctness and app-protocol integration tests
                                                - U: H6-S01
                                              H6-S04 [DEV-RUNTIME] Implement initial plot module (`luvatrix_plot`) and runtime frame renderer integration
                                                - U: H6-S02,H6-S03
                                              H6-S05 [DEV-RUNTIME] Add static + demo plot examples and compile path improvements
                                                - U: H6-S04
                                              H6-S06 [DEV-RUNTIME] Refine 2D layout and add reference-line behavior
                                                - U: H6-S05
                                              H6-S07 [DEV-RUNTIME,QA] Add incremental patch rendering for low-latency legend drag
                                                - U: H6-S06
                                              H6-S08 [DEV-RENDER,ARCH] Standardize Vulkan scaling/blit math contracts for plot rendering stability
                                                - U: H6-S07
                                              H6-S09 [ARCH,DEV-RUNTIME] Add first-party UI component protocol + UI IR schema + frame-rate controller
                                                - U: H6-S08
                                              H6-S10 [DEV-RUNTIME] Stabilize dynamic 2D axis alignment and live plot update behavior
                                                - U: H6-S09
                                              H6-S11 [TEST,QA] Expand plot/UI/runtime test suites and validate integrated behavior
                                                - U: H6-S10
                                              H6-S12 [REL] Close milestone and publish integration rationale
                                                - U: H6-S11
```

H-006 execution evidence:
1. Commit `8d966f5` -> implements H6-S02..H6-S05 baseline plot stack.
2. Commit `0f8d9f3` -> implements H6-S06.
3. Commit `3ef4e14` -> implements H6-S07.
4. Commit `94f77f8` -> implements H6-S08.
5. Commit `2af0337` -> implements H6-S09,H6-S11 partial.
6. Commit `9e1aa60` -> implements H6-S10,H6-S11,H6-S12 completion.
7. Branch provenance: `main` direct integration.

### H-007 Plot Stabilization and Stream Simulation Integration (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H7-S01 [PM] Define dynamic rolling and stream ingestion stability criteria
                                              H7-S02 [ARCH] Specify live-buffer API and fake-stream simulation interface contracts
                                                - U: H7-S01
                                              H7-S03 [TEST] Define reconnect/overlay/rolling regression cases for dynamic plots
                                                - U: H7-S01
                                              H7-S04 [DEV-RUNTIME] Implement dynamic 2D rolling stabilization and reconnect line-overlay fix
                                                - U: H7-S02,H7-S03
                                              H7-S05 [DEV-RUNTIME] Implement fake websocket stream demo and live buffer ingestion API
                                                - U: H7-S04
                                              H7-S06 [DOC] Update plot README and usage guidance for stream demo
                                                - U: H7-S05
                                              H7-S07 [INTG] Merge stabilization and stream branches into `main`
                                                - U: H7-S06
                                              H7-S08 [QA,REL] Validate post-merge behavior and close milestone
                                                - U: H7-S07
```

H-007 execution evidence:
1. Commit `8556c91` -> implements H7-S04 on `codex/plot-module-v0`.
2. Commit `a3fc9ea` -> implements H7-S05,H7-S06 on `codex/plot-module-v0`.
3. Commits `aca4a07`, `50675ea` -> implement H7-S07,H7-S08 merge integration into `main`.
4. Branch provenance: `codex/plot-module-v0` -> `main`.

### H-008 Discord Ops Consolidation under /discord (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H8-S01 [PM] Define Discord operations consolidation scope and success criteria
                                              H8-S02 [ARCH] Define `/ops/discord/{artifacts,docs,ops,scripts}` information architecture
                                                - U: H8-S01
                                              H8-S03 [TEST] Define path-migration validation checks and bootstrap regression checks
                                                - U: H8-S01
                                              H8-S04 [DEV-PLATFORM] Migrate artifacts/docs/ops assets to dedicated `/discord` hierarchy
                                                - U: H8-S02,H8-S03
                                              H8-S05 [DEV-PLATFORM] Update automation scripts and tooling paths to new layout
                                                - U: H8-S04
                                              H8-S06 [DOC] Publish usage/readme guidance for consolidated Discord ops assets
                                                - U: H8-S05
                                              H8-S07 [INTG,QA] Validate bootstrap/posting/checker tooling against migrated structure
                                                - U: H8-S06
                                              H8-S08 [REL] Close consolidation milestone with evidence package
                                                - U: H8-S07
```

H-008 execution evidence:
1. Commit `48c3c02` -> implements H8-S01..H8-S08 (full migration + scripts/docs/assets refresh).
2. Branch provenance: `main` direct integration.

### H-009 Packaging Metadata and Vulkan Preflight Guidance (Historical Replay)
```text
[LOCKED] [READY] [IN-PROGRESS] [REVIEW] [DONE]
                                              H9-S01 [PM] Define package-release readiness and runtime setup guidance criteria
                                              H9-S02 [ARCH] Define publish metadata, optional extras, and native preflight strategy
                                                - U: H9-S01
                                              H9-S03 [TEST] Define dependency/runtime startup verification checks
                                                - U: H9-S01
                                              H9-S04 [DEV-PLATFORM] Add publish metadata and optional dependency extras in package config
                                                - U: H9-S02,H9-S03
                                              H9-S05 [DEV-PLATFORM] Fix runtime dependency set and version bump for release correctness
                                                - U: H9-S04
                                              H9-S06 [DEV-RUNTIME] Add Vulkan runtime preflight helper and backend integration checks
                                                - U: H9-S05
                                              H9-S07 [DOC] Update README/operator guidance for missing native setup remediation
                                                - U: H9-S06
                                              H9-S08 [QA,REL] Validate packaging + startup guidance and close milestone
                                                - U: H9-S07
```

H-009 execution evidence:
1. Commit `f255da9` -> implements H9-S04 (publish metadata + extras).
2. Commit `5fdcad6` -> implements H9-S05 (dependency correction + version bump).
3. Commit `f943653` -> implements H9-S06..H9-S08 (preflight guidance + runtime docs/main wiring + closeout).
4. Branch provenance: `main` direct integration.

### M-001 Discord Operating Baseline
```text
[LOCKED]                     [READY]                        [IN-PROGRESS]                  [REVIEW]                 [DONE]
                                                                 T1 Define success criteria
                                                                    H: PM  U: -
                                                                 T2 Bot baseline config
                                                                    H: DEV-PLATFORM  U: T1
                                                                 T3 Rollout verification
                                                                    H: TEST,INTG  U: T2
                                                                                                T4 Artifact publication
                                                                                                   H: DOC,PM  U: T3
                                                                                                                         T5 Channel architecture + perms
                                                                                                                            H: DEV-PLATFORM  U: T1
```

### M-002 App Protocol Documentation Finalization
```text
[LOCKED]                                [READY]                      [IN-PROGRESS] [REVIEW] [DONE]
T2.4 Operator run examples
  H: DOC,TEST  U: T2.2,T2.3             T2.1 Manifest schema examples
                                         H: ARCH,DOC  U: PM criteria
                                         T2.2 Variant edge cases
                                         H: ARCH,TEST  U: T2.1
                                         T2.3 Compatibility/deprecation policy
                                         H: PM,ARCH,SAFE  U: T2.2
```

### M-003 Vulkan Stabilization
```text
[LOCKED]                                 [READY]                          [IN-PROGRESS] [REVIEW] [DONE]
T3.4 Fallback parity validation
  H: QA,TEST  U: T3.3                    T3.1 Failure mode inventory
                                          H: DEV-RENDER,TEST  U: PM criteria
                                          T3.2 Targeted regression tests
                                          H: TEST,SAFE  U: T3.1
                                          T3.3 Resiliency implementation
                                          H: DEV-RENDER  U: T3.2
```

### M-004 CI Hardening and Flaky Governance
```text
[LOCKED]                               [READY]                           [IN-PROGRESS] [REVIEW] [DONE]
T4.4 Release-readiness summary
  H: INTG,REL,DOC  U: T4.2,T4.3         T4.1 Deterministic gate ownership
                                         H: PM,INTG  U: PM criteria
                                         T4.2 Flaky quarantine workflow
                                         H: INTG,QA  U: T4.1
                                         T4.3 Smoke visibility/reporting
                                         H: DEV-PLATFORM,OBS  U: T4.1
```

### M-005 Audit Retention Lifecycle
```text
[LOCKED]                               [READY]                            [IN-PROGRESS] [REVIEW] [DONE]
T5.4 Operator playbook
  H: DOC,REL  U: T5.2,T5.3              T5.1 Retention defaults
                                         H: ARCH,SAFE,PM  U: PM criteria
                                         T5.2 Prune/report workflow
                                         H: DEV-RUNTIME,INTG  U: T5.1
                                         T5.3 Volume validation
                                         H: TEST,QA  U: T5.2
```

### M-006 Production-Hardening Go/No-Go
```text
[LOCKED]                                           [READY] [IN-PROGRESS] [REVIEW] [DONE]
T6.1 Evidence packet assembly
  H: PM,DOC,INTG  U: M3,M4,M5 complete
T6.2 Open-risk adjudication
  H: SAFE,PM,QA  U: T6.1
T6.3 Go/No-Go decision record
  H: REL,PM,ARCH  U: T6.2
```

### M-007 Cross-Platform Full-Suite Interactive Generalization
```text
[LOCKED]                                [READY]                       [IN-PROGRESS]                               [REVIEW] [DONE]
T7.5 Docs + runbook updates
  H: DOC,PM  U: T7.4                    T7.1 Platform-aware runtime path
                                         H: DEV-RUNTIME,ARCH  U: PM criteria
                                         T7.2 Animation parity verification
                                         H: TEST,QA  U: T7.1
                                         T7.3 Non-macOS system telemetry providers
                                         H: DEV-RUNTIME,SAFE  U: T7.1
                                         T7.4 Regression tests and CI proof
                                         H: TEST,INTG  U: T7.2,T7.3
```

### M-008 Plot + Data UX Foundations (Labels, Bars, Subplots, Scrolling, Table UI)
```text
[LOCKED]                                 [READY]                         [IN-PROGRESS] [REVIEW] [DONE]
T8.6 UX/playbook docs + operator examples
  H: DOC,PM  U: T8.5                     T8.1 Sideways x-axis rule labels for long names
                                          H: DEV-RENDER,ARCH,TEST  U: M-007 baseline
                                          T8.2 Bar chart rendering support
                                          H: DEV-RENDER,TEST  U: T8.1
                                          T8.3 Multi-plot (subplot-like) layout support
                                          H: DEV-RENDER,DEV-RUNTIME,ARCH  U: T8.2
                                          T8.4 Scrolling/viewport navigation
                                          H: DEV-RUNTIME,QA,INTG  U: T8.3
                                          T8.5 Table UI component system (sort/filter/paginate)
                                          H: DEV-RUNTIME,ARCH,TEST  U: T8.4
```

### M-009 Data Workspace UI (Calendar App)
```text
[LOCKED]                              [READY]                           [IN-PROGRESS] [REVIEW] [DONE]
T9.4 Integration docs and acceptance summary
  H: DOC,PM  U: T9.3                   T9.1 Calendar app views + event model
                                        H: DEV-RUNTIME,ARCH,TEST  U: T8.5
                                        T9.2 Calendar workflow integration + workspace sync
                                        H: DEV-RUNTIME,ARCH,TEST  U: T9.1
                                        T9.3 Shared interaction model + regression suite
                                        H: QA,INTG,SAFE  U: T9.2
```

### M-010 Custom Marketbook Dynamic Plotting System
```text
[LOCKED]                                [READY]                             [IN-PROGRESS] [REVIEW] [DONE]
T10.5 Production-readiness packet
  H: REL,PM,DOC  U: T10.4               T10.1 Marketbook schema + ingestion contracts
                                          H: ARCH,DEV-RUNTIME,TEST  U: T9.3
                                          T10.2 Dedicated marketbook renderer (depth/spread/imbalance)
                                          H: DEV-RENDER,DEV-RUNTIME  U: T10.1
                                          T10.3 Streaming update + latency budget enforcement
                                          H: DEV-RUNTIME,QA,INTG  U: T10.2
                                          T10.4 Safety/regression tests + operator playbook
                                          H: SAFE,TEST,DOC  U: T10.3
```

### M-011 Native Gantt + Agile Visualization in Luvatrix
```text
[LOCKED]                                  [READY]                                [IN-PROGRESS] [REVIEW] [DONE]
T11.7 Launch checklist + docs handoff
  H: REL,DOC,PM  U: T11.6                 T11.1 Timeline/task schema contract
                                            H: ARCH,PM,TEST  U: T8.4
                                            T11.2 Gantt renderer core (lanes/axis/dependencies)
                                            H: DEV-RENDER,ARCH  U: T11.1
                                            T11.3 Agile board renderer core (columns/swimlanes/blockers)
                                            H: DEV-RUNTIME,DEV-RENDER  U: T11.1
                                            T11.4 Interaction model (zoom/filter/scroll/click-through)
                                            H: DEV-RUNTIME,QA  U: T11.2,T11.3
                                            T11.5 Export adapters (ASCII/Markdown/PNG) + Discord payload compatibility
                                            H: DEV-RUNTIME,DEV-PLATFORM,INTG  U: T11.4
                                            T11.6 Regression + dependency integrity test suite
                                            H: TEST,SAFE,INTG  U: T11.5
```
M-011 mandatory success criteria:
1. All milestone outputs must comply with first-party Luvatrix App Protocol contracts.
2. Schema/renderer/interaction/export/validation paths must remain first-party module driven and deterministic.
3. No `T11.x` task can move to `Done` without App Protocol compliance evidence and matching test/demo proof.

## 6) Operational Rule for AI Self-Organization

1. Any unlocked task can be claimed by any listed handler.
2. If claimed handler is occupied for > N hours, PM reassigns to backup handler.
3. Each task update must include:
- progress delta
- blocking dependency (if any)
- evidence link
4. No task moves to `Done` without test/safety evidence.
