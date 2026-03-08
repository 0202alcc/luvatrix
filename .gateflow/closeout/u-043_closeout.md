# Objective Summary
U-043 converts rendering v1 planning outputs to deterministic text-only surfaces (`md`/`ascii`) and removes PNG/matplotlib from the v1 execution path.

# Task Final States
- `T-4300`: closeout harness and board baseline established.
- `T-4301`: `render gantt --format md|ascii` implemented.
- `T-4302`: `render board --format md|ascii` implemented.
- `T-4303`: PNG path disabled for v1 and CI expectations updated.
- `T-4304`: deterministic snapshot tests added for text render outputs.

# Evidence
- Task PRs: pending.
- Milestone PR: pending.
- Required checks:
  - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py`
  - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id U-043`

# Determinism
- Render outputs are asserted through snapshot tests for `md` and `ascii`.
- Ordering and formatting are stable for repeated runs over identical ledgers.

# Protocol Compatibility
- Changes are limited to GateFlow v1 CLI/render surfaces and planning artifact generation for v1 text outputs.
- Existing milestone/task/board schema contracts remain unchanged.

# Modularity
- Rendering command wiring is isolated to CLI render handlers.
- Planning API regeneration path uses dedicated renderer bridge modules.

# Residual Risks
- External scripts that still explicitly call PNG utilities may require follow-up migration to text artifacts.
- Snapshot fixtures may need intentional refresh when render contract changes are approved.
