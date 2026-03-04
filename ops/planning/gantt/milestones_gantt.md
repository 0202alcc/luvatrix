# Detailed ASCII Gantt

Canonical schedule source: `ops/planning/gantt/milestone_schedule.json`

```text
                                                                                                   |W01    W02    W03    W04    W05    W06    W07    W08    W09    W10    W11    W12    W13    W14    W15    W16    W17    |
                                                                                                   |02/23  03/02  03/09  03/16  03/23  03/30  04/06  04/13  04/20  04/27  05/04  05/11  05/18  05/25  06/01  06/08  06/15  |
---------------------------------------------------------------------------------------------------+-----------------------------------------------------------------------------------------------------------------------+
APU-020 🧭 Native Gantt + Agile visualization in Luvatrix                                           |                                                               ============================                            | Complete
ARU-016 🌐 Cross-platform full-suite interactive generalization                                     |############################                                                                                           | In Progress
AU-018 🗓️ Data workspace UI (calendar app)                                                         |                                                 ~~~~~~~~~~~~~~                                                        | Planned
AU-019 📈 Custom marketbook dynamic plotting system (integrated with U-021 plots module)            |                                                        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~                                   | Planned
F-001 🧬 Core package transition and repository cleanup                                             |=======                                                                                                                | Complete (2026-02-23)
F-003 ⚡ Runtime safety controller and audit pipeline hardening                                     |=======                                                                                                                | Complete (2026-02-24)
F-011 📜 App protocol docs finalized                                                                |       ==============                                                                                                  | Complete (2026-03-03)
F-014 🛡️ Audit retention lifecycle                                                                 |                            ~~~~~~~~~~~~~~~~~~~~~                                                                      | Planned
F-024 🛰️ Sensor backend performance modernization                                                  |                                                                                           ============================| Complete
FR-004 🧭 Platform variant routing and HDI phase standardization                                    |=======                                                                                                                | Complete (2026-02-26)
P-008 🗂️ Discord ops consolidation under /discord                                                  |=======                                                                                                                | Complete (2026-02-26)
P-010 🧱 Discord governance artifacts and onboarding system                                         |##############                                                                                                         | In Progress
P-013 🧪 CI hardening and flaky governance                                                          |                     ~~~~~~~~~~~~~~~~~~~~~                                                                             | Planned
P-015 🚀 Production-hardening go/no-go review                                                       |                                                 ~~~~~~~~~~~~~~~~~~~~~                                                 | Planned
P-021 📏 Performance baseline and telemetry gates                                                   |                                                                                    ==============                     | Complete
R-002 🖥️ macOS visual runtime foundation merged to main                                            |=======                                                                                                                | Complete (2026-02-23)
R-005 🎯 Rendering fallback, smoke docs, and GPU blit path                                          |=======                                                                                                                | Complete (2026-02-26)
R-012 🎮 Vulkan stabilization                                                                       |              ~~~~~~~~~~~~~~~~~~~~~~~~~~~~                                                                             | Planned
R-022 🧬 Render copy elimination                                                                    |                                                                                    ============================       | Complete (2026-03-03)
R-023 🚚 Vulkan transfer path efficiency                                                            |                                                                                           ============================| Complete (2026-03-03)
R-025 🎛️ Event loop and input scheduling tightening                                                |                                                                                    ============================       | Complete
RF-009 📦 Packaging metadata and Vulkan runtime preflight guidance                                  |=======                                                                                                                | Complete (2026-02-27)
U-007 🔌 Plot stabilization and stream simulation integration                                       |=======                                                                                                                | Complete (2026-02-27)
U-017 📊 UI/UX foundations (text, SVG, table, scrolling, interaction surfaces)                      |                     ##########################################                                                        | In Progress
U-021 📉 Plots module foundations (labels, bars, subplots, dynamic data, financial visualizations)  |                     ########################################################                                          | In Progress
UF-006 📈 Interactive plot module and UI IR integration                                             |=======                                                                                                                | Complete (2026-02-26)
P-026 ✅ Runtime Performance Hardening Closeout Signoff                                             |                                                                      ============================                     | Complete (2026-03-03)

Legend: '=' Complete, '#' In Progress, '~' Planned, '!' At Risk, 'x' Blocked
```

## Milestone Details

### APU-020 🧭 Native Gantt + Agile visualization in Luvatrix
- Status: Complete
- Target window: Week 10-13
- Tasks: `T-1101, T-1102, T-1103, T-1104, T-1105, T-1106, T-1107, T-1108, T-1109, T-1110, T-1111, T-1112, T-1113`
- Lifecycle events:
  - 2026-02-28 closed (framework=kanban_v1) - initial sprint closure
  - 2026-03-01 reopened (framework=kanban_v1) - reopened for additional compliance work
  - 2026-03-03 active (framework=gateflow_v1) - framework migration cycle
- Success criteria:
  - Must comply with first-party Luvatrix App Protocol contracts.
  - Schema, renderer, interaction, export, and validation flows must remain first-party module driven and deterministic.
  - Do not mark complete without task-level App Protocol compliance evidence plus passing test/demo evidence.
- Acceptance checks:
  - `T-1101`: Schema contract includes milestone/task/dependency/owner fields with strict status validation; tests prove canonical parse/load and first-party type export.
  - `T-1102`: Gantt renderer produces deterministic axis/status/dependency output with collapsed/expanded lanes and is callable from first-party planning modules.
  - `T-1103`: Agile renderer produces deterministic board columns/swimlanes/blocker views and has no third-party UI runtime dependency.
  - `T-1104`: Filtering/zoom/scroll/click-through interactions are deterministic, clamped, and compatible with first-party planning state types.
  - `T-1105`: Export adapters produce ASCII/Markdown/PNG artifacts and Discord payload manifests from first-party planning models.
  - `T-1106`: Validation suite enforces dependency integrity and render consistency; App Protocol compliance evidence is required to clear completion.

### ARU-016 🌐 Cross-platform full-suite interactive generalization
- Status: In Progress
- Target window: Week 1-4
- Tasks: `T-701, T-702, T-703, T-704`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### AU-018 🗓️ Data workspace UI (calendar app)
- Status: Planned
- Target window: Week 8-9
- Tasks: `T-901, T-902`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### AU-019 📈 Custom marketbook dynamic plotting system (integrated with U-021 plots module)
- Status: Planned
- Target window: Week 9-12
- Tasks: `T-1001, T-1002, T-1003, T-1004`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle
  - 2026-03-03 reopened (framework=gateflow_v1) - integrated dependency path added for U-021 plot module outputs

### F-001 🧬 Core package transition and repository cleanup
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-23
- Tasks: `A-H001-01, A-H001-02`
- Lifecycle events:
  - 2026-02-23 closed (framework=legacy-kanban) - historical completion

### F-003 ⚡ Runtime safety controller and audit pipeline hardening
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-24
- Tasks: `A-H003-01, A-H003-02`
- Lifecycle events:
  - 2026-02-24 closed (framework=legacy-kanban) - historical completion

### F-011 📜 App protocol docs finalized
- Status: Complete
- Target window: Week 2-3
- Completed on: 2026-03-03
- Tasks: `T-201, T-202, T-203, T-204, T-205, T-206, T-207, T-208, T-209, T-210, T-211, T-212, T-213, T-214, T-215, T-216, T-217, T-218, T-219, T-2701, T-2702, T-2703`
- Lifecycle events:
  - 2026-03-03 closed (framework=kanban_v1) - documentation sprint closed
  - 2026-03-03 reopened (framework=gateflow_v1) - reopened for GateFlow-aligned continuation
  - 2026-03-03 reopened (framework=gateflow_v1) - performance follow-up scope opened for incremental present and sensor/runtime semantics
  - 2026-03-03 closed (framework=gateflow_v1) - follow-up scope complete; tasks T-2701/T-2702/T-2703 done and merged to main

### F-014 🛡️ Audit retention lifecycle
- Status: Planned
- Target window: Week 5-7
- Tasks: `T-501, T-502, T-503`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### F-024 🛰️ Sensor backend performance modernization
- Status: Complete
- Target window: Week 14-17
- Tasks: `T-2501, T-2502, T-2503, T-2504`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - planned from architect performance directives
  - 2026-03-03 closed (framework=gateflow_v1) - completed and verified on main with required checks

### FR-004 🧭 Platform variant routing and HDI phase standardization
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-26
- Tasks: `A-H004-01, A-H004-02`
- Lifecycle events:
  - 2026-02-26 closed (framework=legacy-kanban) - historical completion

### P-008 🗂️ Discord ops consolidation under /discord
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-26
- Tasks: `A-H008-01, A-H008-02`
- Lifecycle events:
  - 2026-02-26 closed (framework=legacy-kanban) - historical completion

### P-010 🧱 Discord governance artifacts and onboarding system
- Status: In Progress
- Target window: Week 1-2
- Tasks: `T-101, T-102, T-103`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### P-013 🧪 CI hardening and flaky governance
- Status: Planned
- Target window: Week 4-6
- Tasks: `T-401, T-402, T-403`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### P-015 🚀 Production-hardening go/no-go review
- Status: Planned
- Target window: Week 8-10
- Tasks: `T-601, T-602, T-603`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### P-021 📏 Performance baseline and telemetry gates
- Status: Complete
- Target window: Week 13-14
- Tasks: `T-2101, T-2102, T-2103, T-2104`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - performance modernization baseline kickoff
  - 2026-03-03 closed (framework=gateflow_v1) - gateflow compliance audit complete; all P-021 tasks verified done on main

### R-002 🖥️ macOS visual runtime foundation merged to main
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-23
- Tasks: `A-H002-01, A-H002-02`
- Lifecycle events:
  - 2026-02-23 closed (framework=legacy-kanban) - historical completion

### R-005 🎯 Rendering fallback, smoke docs, and GPU blit path
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-26
- Tasks: `A-H005-01, A-H005-02`
- Lifecycle events:
  - 2026-02-26 closed (framework=legacy-kanban) - historical completion

### R-012 🎮 Vulkan stabilization
- Status: Planned
- Target window: Week 3-6
- Tasks: `T-301, T-302, T-303, T-304`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - active milestone in current planning cycle

### R-022 🧬 Render copy elimination
- Status: Complete
- Target window: Week 13-16
- Completed on: 2026-03-03
- Tasks: `T-2201, T-2202, T-2203, T-2204`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - planned from architect performance directives

### R-023 🚚 Vulkan transfer path efficiency
- Status: Complete
- Target window: Week 14-17
- Completed on: 2026-03-03
- Tasks: `T-2401, T-2402, T-2403, T-2404`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - planned from architect performance directives

### R-025 🎛️ Event loop and input scheduling tightening
- Status: Complete
- Target window: Week 13-16
- Tasks: `T-2601, T-2602, T-2603, T-2604`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - planned from architect performance directives
  - 2026-03-03 closed (framework=gateflow_v1) - gateflow compliance audit complete; tasks done and verified on main

### RF-009 📦 Packaging metadata and Vulkan runtime preflight guidance
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-27
- Tasks: `A-H009-01, A-H009-02`
- Lifecycle events:
  - 2026-02-27 closed (framework=legacy-kanban) - historical completion

### U-007 🔌 Plot stabilization and stream simulation integration
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-27
- Tasks: `A-H007-01, A-H007-02`
- Lifecycle events:
  - 2026-02-27 closed (framework=legacy-kanban) - historical completion

### U-017 📊 UI/UX foundations (text, SVG, table, scrolling, interaction surfaces)
- Status: In Progress
- Target window: Week 4-9
- Tasks: `T-804, T-805, T-834, T-835, T-836, T-837, T-838, T-839, T-840, T-2301, T-2302, T-2303, T-2304, T-2305`
- Lifecycle events:
  - 2026-03-01 closed (framework=kanban_v1) - sprint closure
  - 2026-03-01 reopened (framework=kanban_v1) - follow-up tasks added
  - 2026-03-03 active (framework=gateflow_v1) - framework migration cycle
  - 2026-03-03 reopened (framework=gateflow_v1) - scope split: plotting work moved into U-021 while UI/UX foundations remain in U-017

### U-021 📉 Plots module foundations (labels, bars, subplots, dynamic data, financial visualizations)
- Status: In Progress
- Target window: Week 4-11
- Tasks: `T-801, T-802, T-803, T-821, T-822`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - split from U-017 to isolate plotting stack and integrate with AU-019

### UF-006 📈 Interactive plot module and UI IR integration
- Status: Complete
- Target window: Week 1-1
- Completed on: 2026-02-26
- Tasks: `A-H006-01, A-H006-02`
- Lifecycle events:
  - 2026-02-26 closed (framework=legacy-kanban) - historical completion

### P-026 ✅ Runtime Performance Hardening Closeout Signoff
- Status: Complete
- Target window: Week 11-14
- Completed on: 2026-03-03
- Tasks: `T-2801, T-2802, T-2803, T-2804, T-2805`
- Lifecycle events:
  - 2026-03-03 active (framework=gateflow_v1) - closeout signoff milestone created from architecture/system no-go review
  - 2026-03-03 active (framework=gateflow_v1) - architect decision package imported: Vulkan deferred with guardrails; thresholds/invariants/exit gates finalized
- Success criteria:
  - All closeout tasks complete with consolidated evidence package.
  - Boundary contracts are re-validated: RenderTarget, SensorProvider, HDIThread/SensorManagerThread separation, and protocol/AppContext compatibility.
  - Determinism and compatibility checks pass under a unified reproducible benchmark protocol.
  - Final architecture closeout can issue Go confidence >= 0.85.
- Acceptance checks:
  - `T-2801`: Unified benchmark matrix with deterministic seeds and adjusted thresholds (input p95<=33.3ms, p99<=50ms, incremental>=90%, resize recovery<=1.0s) emits per-scenario verdicts.
  - `T-2802`: Vulkan decision is DEFERRED_WITH_GUARDRAILS with normative text, disallowed wording controls, fallback parity evidence, and boundary integrity proof.
  - `T-2803`: Snapshot immutability and revisioned-read invariants are specified and validated with zero-mismatch determinism replay requirements.
  - `T-2804`: Incremental-present scenario targets/caps are met, or approved exceptions are documented within hard caps and artifact checks pass.
  - `T-2805`: Final evidence packet reconciles board/task/artifact state and passes architecture Go/No-Go checklist without unresolved blockers.

## Branching and Merge Gate Policy
1. Each milestone is implemented first on its own milestone branch.
2. Cross-milestone dependencies are resolved by merge-to-main or explicit branch pull/cherry-pick with traceability notes.
3. A milestone is not Complete until merged into main and required tests pass on main.

## Weekly Update Format
1. Milestone ID
2. Planned vs actual progress
3. New risks/blockers
4. Dependency impact
5. Branch integration status
6. Main-branch test status
7. Next-week focus

Update policy: edit `ops/planning/gantt/milestone_schedule.json` and rerun posting scripts.