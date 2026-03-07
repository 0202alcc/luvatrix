# P-040 Closeout Packet

## Objective Summary

Milestone `P-040` locks the standalone GateFlow CLI v1 specification so downstream implementation milestones are decision-complete before extraction and refactor work begins.

## Task Final States

1. `T-4000`: closeout harness and milestone execution board contract defined.
2. `T-4001`: v1 CLI command matrix finalized (`init`, `resources`, `validate`, `render`, `config`, `api` shim).
3. `T-4002`: `.gateflow/` canonical schema and deterministic JSON format rules frozen.
4. `T-4003`: profile contract (`minimal`, `discord`, `enterprise`) and scaffold boundaries defined.
5. `T-4004`: policy contract (`protected_branch`, `done_gate`, harness-warning mode) finalized.
6. `T-4005`: ADR/spec packet published for downstream implementation teams.

## Evidence

1. `ops/planning/agile/m040_execution_board.md`
2. `ops/planning/specs/gateflow_v1/t-4001_command_matrix.md`
3. `ops/planning/specs/gateflow_v1/t-4002_gateflow_schema_contract.md`
4. `ops/planning/specs/gateflow_v1/t-4003_profile_contract.md`
5. `ops/planning/specs/gateflow_v1/t-4004_policy_contract.md`
6. `ops/planning/adr/ADR-011-gateflow-v1-program-setup-spec-lock.md`
7. Validator commands to run at integration:
  - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
  - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id P-040`

## Determinism

1. Canonical JSON contract freezes key ordering, formatting, and ledger id schemas.
2. Command and policy contracts define stable exit semantics and deterministic error ordering.
3. Profile overlays are constrained to additive behavior over canonical base contracts.

## Protocol Compatibility

1. The `api` shim lane preserves compatibility with planning-api style workflows.
2. Policy contracts align with GateFlow done-gate telemetry and protected-branch semantics.

## Modularity

1. Specification is split into focused command/schema/profile/policy modules.
2. ADR links all modules as a single normative packet for downstream milestones.

## Residual Risks

1. Runtime conformance remains dependent on downstream implementation milestones.
2. Any scope extension beyond v1 boundaries requires ADR amendment before implementation.

## Closeout Harness Metric

1. Metric id: `p-040-closeout-v1`.
2. Scoring components: `correctness`, `safety`, `compatibility`, `evidence`.
3. Go threshold: `85`.
4. Hard no-go conditions: required check failure, closeout validation failure, unresolved high-severity risk without waiver.

## Closeout Harness Metric

1. Metric id: `p-040-closeout-v1`.
2. Scoring components: `correctness`, `safety`, `compatibility`, `evidence`.
3. Go threshold: `85`.
4. Hard no-go conditions: required check failure, closeout validation failure, unresolved high-severity risk without waiver.
