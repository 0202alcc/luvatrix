# ADR-INDEX: Architecture Decision Record Index

This index tracks major decisions with alternatives and rationale.

## Status Legend
1. Proposed
2. Accepted
3. Superseded
4. Rejected

## ADR Entries

1. `ADR-001` macOS-first Phase 1 strategy
- Status: Accepted
- Date: 2026-02-25
- Summary: Prioritize macOS renderer/runtime hardening before broader platform rollout.
- Linked evidence: `planning.md`, runtime implementation/tests

2. `ADR-002` Hybrid Gantt + Team Agile delivery model
- Status: Accepted
- Date: 2026-02-25
- Summary: Use milestone-level Gantt with team-level Agile boards linked via `M-###`.
- Linked evidence: `ops/discord/discord.md`, artifact pack

3. `ADR-003` RFC+ADR governance for major changes
- Status: Accepted
- Date: 2026-02-25
- Summary: Major changes require written proposal, decision record, and evidence links.
- Linked evidence: `ops/discord/discord.md`

4. `ADR-004` Embedded + central quality model
- Status: Accepted
- Date: 2026-02-25
- Summary: Keep quality ownership in teams with centralized standards/gates.
- Linked evidence: `planning.md`

5. `ADR-005` Single LLM backend with multi-identity AI bots
- Status: Accepted
- Date: 2026-02-25
- Summary: Reduce cost while preserving role-specific contexts and controls.
- Linked evidence: `ops/discord/discord.md` bot strategy

6. `ADR-006` MatrixBuffer and Camera Overlay terminology
- Status: Accepted
- Date: 2026-03-01
- Summary: Standardize naming so visible output is always `MatrixBuffer` and top-pinned UI is `CameraOverlayLayer`.
- Linked evidence: `ops/planning/adr/ADR-006-matrixbuffer-cameraoverlay-terminology.md`, `ops/planning/agile/m008_execution_board.md`

7. `ADR-007` Plane composition model
- Status: Accepted
- Date: 2026-03-01
- Summary: Define deterministic composition via global plane z, local component z, and camera-overlay dominance.
- Linked evidence: `ops/planning/adr/ADR-007-plane-composition-model.md`, `ops/planning/agile/m008_execution_board.md`

## New ADR Template
1. Context
2. Decision
3. Alternatives considered
4. Rationale
5. Consequences
6. Links to PR/tests/reports
7. Owner and approver
