# Objective Summary
- Deliver deterministic migration tooling from `ops/planning/*` to `.gateflow/*`.
- Ensure imported data validates with `gateflow validate all` and emits actionable drift remediation.

# Task Final States
- `T-4600`: In progress in this packet; task PR evidence added after merge.
- `T-4601`: Pending.
- `T-4602`: Pending.
- `T-4603`: Pending.
- `T-4604`: Pending.

# Evidence
- Task PRs: pending.
- Milestone PR: pending.
- Validation command outputs: pending.

# Determinism
- Import output artifacts and drift reports must be stable for identical source inputs.

# Protocol Compatibility
- Mapping must preserve milestone/task/board/backlog/closeout semantics from `ops/planning`.

# Modularity
- Migration logic should remain isolated to standalone `gateflow` package modules.

# Residual Risks
- `uv` command runtime panic in this environment requires `python3` fallback for local execution.
