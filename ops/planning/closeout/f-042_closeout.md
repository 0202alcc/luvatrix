# Objective Summary
- Deliver a resource-first `gateflow` CLI with deterministic `.gateflow/` scaffolding and profile overlays.
- Preserve endpoint-style compatibility through a temporary `api METHOD /resource` shim.
- Keep policy controls for protected branches, defaults, and render behavior in canonical workspace config.

# Task Final States
- `T-4200` Done.
- `T-4201` In Progress.
- `T-4202` In Progress.
- `T-4203` In Progress.
- `T-4204` In Progress.
- `T-4205` In Progress.

# Evidence
- Task PRs:
  - `T-4200`: pending
  - `T-4201`: pending
  - `T-4202`: pending
  - `T-4203`: pending
  - `T-4204`: pending
  - `T-4205`: pending
- Validation commands:
  - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` -> pending
  - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-042` -> pending

# Determinism
- CLI writes canonical UTF-8 JSON with stable key ordering and a single trailing newline.
- `init` and config rendering output are idempotent for equal inputs.

# Protocol Compatibility
- Temporary `gateflow api METHOD /resource` shim supports endpoint-style migration workflows.
- Resource-first commands map to canonical ledgers without changing ID schema contracts.

# Modularity
- CLI command parsing, workspace I/O, resource services, and shim handling are isolated into dedicated modules.
- Resource mutations route through shared services used by both resource-first and API shim commands.

# Residual Risks
- Shim compatibility scope is bounded to local workspace resources and may require expansion during extraction milestone `F-045`.
- Profile migrations are intentionally conservative; explicit migration command remains out of scope for v1.
