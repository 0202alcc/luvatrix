# ADR-011: GateFlow Standalone CLI v1 Program Setup and Spec Lock

- Status: Accepted
- Date: 2026-03-07
- Milestone: P-040
- Tasks: T-4000, T-4001, T-4002, T-4003, T-4004, T-4005
- Owner: Platform/Protocol

## 1) Context

Downstream GateFlow productization milestones depend on a fixed v1 contract. Without a locked command/data/policy surface, implementation milestones would encode divergent assumptions and increase rework risk.

## 2) Decision

Freeze and publish the v1 specification packet with the following non-negotiable artifacts:
1. Command matrix (`init`, `resources`, `validate`, `render`, `config`, `api` shim).
2. `.gateflow/` canonical schema and deterministic JSON formatting rules.
3. Profile contract (`minimal`, `discord`, `enterprise`) and scaffold boundaries.
4. Policy contract (`protected_branch`, `done_gate`, harness-warning mode).
5. Milestone closeout evidence harness for decision-complete handoff.

## 3) Normative Packet

1. [T-4001 Command Matrix](../specs/gateflow_v1/t-4001_command_matrix.md)
2. [T-4002 Schema Contract](../specs/gateflow_v1/t-4002_gateflow_schema_contract.md)
3. [T-4003 Profile Contract](../specs/gateflow_v1/t-4003_profile_contract.md)
4. [T-4004 Policy Contract](../specs/gateflow_v1/t-4004_policy_contract.md)
5. [P-040 Closeout Packet](../closeout/p-040_closeout.md)

## 4) Consequences

Positive:
1. Downstream milestones can implement against a stable v1 boundary.
2. Deterministic schema/format rules reduce review noise and migration ambiguity.
3. Policy behavior is explicit and testable.

Trade-offs:
1. v1 scope is intentionally constrained and excludes plugin/runtime extension lanes.
2. Any additional command/profile/policy behavior now requires explicit ADR amendment.

## 5) Guardrails

1. No downstream milestone may alter v1 command names or required subcommands without ADR update.
2. No profile may alter canonical key ordering, id schema, or done-gate semantics.
3. Compatibility shims must preserve deterministic response envelopes.

## 6) Implementation Handoff

Downstream implementation teams must consume this packet in the following order:
1. Command surface (`T-4001`) and schema contract (`T-4002`).
2. Profile contract (`T-4003`) and policy contract (`T-4004`).
3. Closeout harness and evidence criteria (`T-4000`, closeout packet).

## 6) Implementation Handoff

Downstream implementation teams must consume this packet in the following order:
1. Command surface (`T-4001`) and schema contract (`T-4002`).
2. Profile contract (`T-4003`) and policy contract (`T-4004`).
3. Closeout harness and evidence criteria (`T-4000`, closeout packet).
