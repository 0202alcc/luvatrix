# M-002 Execution Board

Milestone: `M-002` App protocol docs finalized
Epic: `E-201`
Task chain: `T-201 -> T-202 -> T-203`
Last updated: `2026-03-01`

## Backlog
1. None.

## Ready
1. None.

## In Progress
1. None.

## Review
1. None.

## Done
1. `T-201` Add complete variant-routing examples to protocol docs.
- Evidence:
  `PYTHONPATH=. uv run pytest tests/test_app_runtime.py tests/test_protocol_governance.py tests/test_unified_runtime.py` (pass, 29 tests)
2. `T-202` Add compatibility/deprecation matrix and migration notes.
- Evidence:
  `PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py` (covered by suite above, pass)
3. `T-203` Add operator runbook examples and troubleshooting appendix.
- Evidence:
  `PYTHONPATH=. uv run pytest tests/test_unified_runtime.py tests/test_app_runtime.py` (covered by suite above, pass)

## Evidence Log
1. `2026-03-01`: Added `docs/app_protocol_variants_guide.md` with variant precedence, manifest snippets, run commands, unsupported-platform and bad-module-root failure cases.
2. `2026-03-01`: Added `docs/app_protocol_compatibility_policy.md` with protocol matrix, bounds behavior, deprecation lifecycle, and migration checklist/examples.
3. `2026-03-01`: Added `docs/app_protocol_operator_runbook.md` with operator cookbook, troubleshooting tree, incidents/recovery, and audit verification steps.
4. `2026-03-01`: Linked new protocol docs from `docs/app_protocol.md` and `README.md`.
5. `2026-03-01`: Updated task statuses via planning API:
   `T-201/T-202/T-203 -> Done`, `M-002 -> In Progress`.
6. `2026-03-01`: Validation and regression verification passed:
   `PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py` (`29 passed`).
