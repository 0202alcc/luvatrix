# Milestone ID Migration

This project migrated from legacy milestone IDs (`H-###`, `M-###`) to the
lettered schema:

`<1-3 letters>-<3 digits>`

Letter taxonomy:

1. `A` app projects
2. `R` rendering backend
3. `F` first-party protocols/systems
4. `U` UI/UX tools
5. `P` project management
6. `X` uncategorized/other

Combined IDs are allowed (up to 3 letters), with the primary letter first.

## Legacy -> New Mapping

1. `H-001` -> `F-001`
2. `H-002` -> `R-002`
3. `H-003` -> `F-003`
4. `H-004` -> `FR-004`
5. `H-005` -> `R-005`
6. `H-006` -> `UF-006`
7. `H-007` -> `U-007`
8. `H-008` -> `P-008`
9. `H-009` -> `RF-009`
10. `M-001` -> `P-010`
11. `M-002` -> `F-011`
12. `M-003` -> `R-012`
13. `M-004` -> `P-013`
14. `M-005` -> `F-014`
15. `M-006` -> `P-015`
16. `M-007` -> `ARU-016`
17. `M-008` -> `U-017`
18. `M-009` -> `AU-018`
19. `M-010` -> `AU-019`
20. `M-011` -> `APU-020`

## Lifecycle Tracking

Each milestone now records lifecycle transitions in:

- `ops/planning/gantt/milestone_schedule.json -> milestones[].lifecycle_events`

Use these events to track close/reopen cycles and agile framework changes over time.
