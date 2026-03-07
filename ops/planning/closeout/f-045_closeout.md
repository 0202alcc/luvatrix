# Objective Summary
- Extract GateFlow implementation from Luvatrix into a dedicated standalone `gateflow` package/repo layout.
- Preserve deterministic CLI, planning resources workflow, and validation/render behavior.
- Provide pre-release distribution path and installation docs for `uvx` now, `pipx` next.

# Task Final States
- `T-4500` In Progress.
- `T-4501` Not Started.
- `T-4502` Not Started.
- `T-4503` Not Started.
- `T-4504` Not Started.
- `T-4505` Not Started.

# Evidence
- Task PRs:
  - `T-4500`: pending
  - `T-4501`: pending
  - `T-4502`: pending
  - `T-4503`: pending
  - `T-4504`: pending
  - `T-4505`: pending
- Milestone PR: pending
- Validation commands:
  - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` -> pending
  - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-045` -> pending

# Determinism
- Standalone package must keep deterministic JSON write/read behavior and stable CLI output formatting.
- Snapshot-based rendering behavior must remain stable against committed fixtures.

# Protocol Compatibility
- Preserve GateFlow resource schema and command semantics from previous milestones.
- Maintain compatibility for resource-first CLI usage and temporary API shim usage where documented.

# Modularity
- Package extraction isolates CLI/workspace/validation/render/resource services in dedicated module boundaries.
- Luvatrix runtime modules remain decoupled from standalone package internals.

# Residual Risks
- Packaging behavior for `uvx`/`pipx` may diverge across environments until release matrix is broadened.
- Full migration tooling is intentionally out of scope for `F-045` and continues in `F-046`.
