# A-037 Closeout

## Objective Summary
- A-037 delivers a macOS-first manifest-configurable debug policy that preserves existing app compatibility by default while requiring explicit non-mac stub declarations.
- This phase evaluates Go/No-Go in macOS context only and records planned reopen intent for broader platform/device coverage.

## Task Final States
- `T-2923`: In progress in this packet revision; closeout harness and evidence contract defined.
- `T-2910`: Pending implementation in this packet revision; will provide manifest policy parser, compatibility defaults, and test evidence.

## Evidence
- Required command set:
  - `uv run pytest tests -k "debug_manifest or legacy_debug_conformance" -q`
  - `uv run python ops/planning/api/validate_closeout_evidence.py --milestone-id P-026`
  - `uv run python ops/planning/agile/validate_milestone_task_links.py`
- Evidence logs and output excerpts will be finalized in the milestone completion revision of this packet.

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
