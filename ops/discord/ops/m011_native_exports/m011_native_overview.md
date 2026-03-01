# Native Planning Export

## Gantt (Expanded)

```text
Luvatrix Milestone Gantt (Historical + Active + Planned)
Baseline start: 2026-02-23 | mode=expanded
Status colors: Planned=#94A3B8, In Progress=#2563EB, At Risk=#F59E0B, Blocked=#DC2626, Complete=#16A34A
Weeks:  W01W02W03W04W05W06W07W08W09W10W11W12W13
Dates:  02/2303/0203/0903/1603/2303/3004/0604/1304/2004/2705/0405/1105/18
H-001 Core package transition and repository cleanup                           |==                        | Complete (#16A34A)
H-002 macOS visual runtime foundation merged to main                           |==                        | Complete (#16A34A)
H-003 Runtime safety controller and audit pipeline hardening                   |==                        | Complete (#16A34A)
H-004 Platform variant routing and HDI phase standardization                   |==                        | Complete (#16A34A)
H-005 Rendering fallback, smoke docs, and GPU blit path                        |==                        | Complete (#16A34A)
H-006 Interactive plot module and UI IR integration                            |==                        | Complete (#16A34A)
H-007 Plot stabilization and stream simulation integration                     |==                        | Complete (#16A34A)
H-008 Discord ops consolidation under /discord                                 |==                        | Complete (#16A34A)
H-009 Packaging metadata and Vulkan runtime preflight guidance                 |==                        | Complete (#16A34A)
M-001 Discord governance artifacts and onboarding system                       |####                      | In Progress (#2563EB) deps=H-008
M-007 Cross-platform full-suite interactive generalization                     |########                  | In Progress (#2563EB) deps=H-006,H-009
M-002 App protocol docs finalized                                              |  ~~~~                    | Planned (#94A3B8) deps=M-001
M-003 Vulkan stabilization                                                     |    ~~~~~~~~              | Planned (#94A3B8) deps=M-002,M-007
M-004 CI hardening and flaky governance                                        |      ~~~~~~              | Planned (#94A3B8) deps=M-002
M-008 Plot + data UX foundations (labels, bars, subplots, scrolling, table UI) |      ##########          | In Progress (#2563EB) deps=M-007
M-005 Audit retention lifecycle                                                |        ~~~~~~            | Planned (#94A3B8) deps=M-004
M-009 Data workspace UI (calendar app)                                         |              ~~~~        | Planned (#94A3B8) deps=M-008
M-006 Production-hardening go/no-go review                                     |              ~~~~~~      | Planned (#94A3B8) deps=M-003,M-004,M-005
M-010 Custom marketbook dynamic plotting system                                |                ~~~~~~~~  | Planned (#94A3B8) deps=M-008,M-009
M-011 Native Gantt + Agile visualization in Luvatrix                           |                  ########| In Progress (#2563EB) deps=M-008

Dependency lines:
   H-008 -> M-001  |>-                        | overlap
   M-001 -> M-002  |  >-                      | overlap
   M-002 -> M-003  |    >-                    | overlap
   M-007 -> M-003  |    >---                  | overlap
   M-002 -> M-004  |    -->-                  | ok
   M-004 -> M-005  |        >---              | overlap
   M-003 -> M-006  |          ---->-          | ok
   M-004 -> M-006  |          ---->-          | ok
   M-005 -> M-006  |            -->-          | ok
   H-006 -> M-007  |>-                        | overlap
   H-009 -> M-007  |>-                        | overlap
   M-007 -> M-008  |      >-                  | overlap
   M-008 -> M-009  |              >-          | overlap
   M-008 -> M-010  |              -->-        | ok
   M-009 -> M-010  |                >-        | overlap
   M-008 -> M-011  |              ---->-      | ok
```

## Agile Board

# Luvatrix Milestone Gantt (Historical + Active + Planned) Agile Board

Lane mode: `milestone`

## Swimlane `M-011`
| Backlog | Ready | In Progress | Review | Done |
|---|---|---|---|---|
| - | - | T-1101 Define canonical timeline/task schema for Gantt + Agile c…<br>T-1102 Build native Luvatrix Gantt renderer. (deps=T-1101)<br>T-1103 Build native Luvatrix Agile board renderer. (deps=T-1102)<br>T-1104 Add interaction layer (filtering, zoom/scroll, click-thro… (deps=T-1103)<br>T-1105 Add export adapters (ASCII/Markdown/PNG) and Discord payl… (deps=T-1104)<br>T-1106 Add validation suite for render correctness and dependenc… (deps=T-1105) | - | - |
