# A-037 Closeout

## Objective Summary
- A-037 delivers a macOS-first manifest-configurable debug policy that preserves existing app compatibility by default while requiring explicit non-mac stub declarations.
- This phase evaluates Go/No-Go in macOS context only and records planned reopen intent for broader platform/device coverage.

## Task Final States
- `T-2923`: Done. Closeout harness and evidence contract are defined and integrated in A-037 execution board + packet.
- `T-2910`: Done. Manifest debug policy parser/validator is implemented with legacy-compat defaults and explicit non-mac stub declarations.

## Evidence
- Required command set:
  - `uv run pytest tests -k "debug_manifest or legacy_debug_conformance" -q`
  - `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026`
  - `uv run python ops/planning/agile/validate_milestone_task_links.py`
- Executed evidence (milestone branch):
  - `PYTHONPATH=. uv run pytest tests -k "debug_manifest or legacy_debug_conformance" -q`
    - Result: `5 passed, 414 deselected`
  - `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026`
    - Result: `validation: PASS (evidence)`
  - `uv run python ops/planning/agile/validate_milestone_task_links.py`
    - Result: `validation: PASS (checked 39 milestones against 175 active + 19 archived tasks)`
  - `uv run python ops/planning/api/validate_closeout_packet.py --milestone-id A-037`
    - Result: `validation: PASS (ops/planning/closeout/a-037_closeout.md)`

## Determinism
- Manifest debug policy parsing is deterministic for fixed TOML inputs.
- Non-mac behavior is deterministic and explicit through capability-stub declarations in this phase.

## Protocol Compatibility
- Existing app manifests without a debug policy block remain compatibility-safe and unchanged by default.
- Policy parsing is version-gated and rejects unsupported policy schema revisions.

## Modularity
- Debug policy parsing/validation is isolated in runtime manifest handling and covered by targeted unit tests.
- Platform behavior declarations remain capability-matrix driven for explicit extension in later reopen phases.

## Residual Risks
- Non-mac support remains stubs in this phase; full adapter parity requires planned reopen follow-up.
- Expanded device/software compatibility validation is deferred to the planned reopen milestone cycle.
- Go/No-Go (macOS scope only): **GO**
  - `legacy_compat`: 100
  - `policy_correctness`: 95
  - `p026_non_regression`: 100
  - Composite score (0.4/0.3/0.3): `98.5` (threshold `>= 90`)
- Planned reopen intent: reopen A-037 for Windows/Linux/device/software expansion once adapter implementations and parity tests are scoped.
