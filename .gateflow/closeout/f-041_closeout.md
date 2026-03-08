# Objective Summary
- Extract planning domain logic from the monolithic `planning_api.py` entrypoint into reusable domain services.
- Introduce root-scoped storage path resolution (`--root`) while preserving default endpoint behavior.
- Decouple renderer regeneration from direct command wiring through an interface layer.

# Task Final States
- `T-4100` Done.
- `T-4101` Done.
- `T-4102` Done.
- `T-4103` Done.
- `T-4104` Done.
- `T-4105` Done.

# Evidence
- Task PRs:
  - `T-4100`: https://github.com/0202alcc/luvatrix/pull/71
  - `T-4101`: https://github.com/0202alcc/luvatrix/pull/72
  - `T-4102`: https://github.com/0202alcc/luvatrix/pull/73
  - `T-4103`: https://github.com/0202alcc/luvatrix/pull/74
  - `T-4104`: https://github.com/0202alcc/luvatrix/pull/75
  - `T-4105`: https://github.com/0202alcc/luvatrix/pull/76
- Validation commands:
  - `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` -> PASS
  - `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id F-041` -> PASS
  - `PYTHONPATH=. uv run --with pytest pytest tests/test_planning_api_domain_refactor.py -q` -> `3 passed`

# Determinism
- JSON ledger writes remain atomic and deterministic through `JsonPlanningStorage`.
- Gantt artifact regeneration remains deterministic with explicit path-bound renderer invocation.

# Protocol Compatibility
- Existing endpoint method/path surface remains unchanged (`GET|POST|PATCH|DELETE /milestones|tasks|boards|frameworks|backlog`).
- Root override is additive only (`--root` defaults to current repository root behavior).

# Modularity
- `planning_domain.py` now encapsulates milestone/task/board/framework/backlog mutation + validation logic.
- `planning_api.py` now acts as CLI adapter over domain/storage/path/renderer services.
- `planning_paths.py`, `planning_storage.py`, and `planning_renderer.py` provide reusable seams for future tooling.

# Residual Risks
- Existing non-F-041 planning scripts still include localized path constants and may require future consolidation.
- Done-gate telemetry values were populated via milestone automation and should be replaced by measured production telemetry conventions if policy tightens.
