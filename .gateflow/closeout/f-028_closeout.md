# Objective Summary
- Establish F-028 go/no-go contract for Planes v2 schema and cross-file validation.
- Define deterministic evidence harness for project `multi_plane_layout` covering split-file layout validation and strict invariant enforcement.

# Task Final States
- `T-3420`: Integration Ready. Harness, evidence command surface, and blocker criteria are defined.
- `T-3403`: Pending implementation.
- `T-3404`: Pending implementation.
- `T-3405`: Pending implementation.
- `T-3426`: Pending implementation.
- `T-3427`: Pending implementation.

# Evidence
- Required validation command profile:
  - `uv run pytest tests -k "planes_schema_validation or planes_cross_file_invariants" -q`
  - `uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q`
  - `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
  - `uv run python ops/planning/agile/validate_milestone_task_links.py`
  - `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate links`
  - `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate closeout`

# Determinism
- Split-file validation output must be stable under identical inputs and deterministic sort order.
- Evidence manifests must carry deterministic artifact digests and stable path mapping.

# Protocol Compatibility
- Strict mode is the CI/release default for Planes v2 split-file validation.
- Permissive behavior is limited to explicit compatibility windows and must emit diagnostics.

# Modularity
- Validation layer responsibilities:
  - schema checks
  - cross-file invariant checks
  - strict/permissive policy diagnostics
  - visual evidence contract checks
- Runtime and compiler behavior remain outside validator scope except for interface-level contract checks.

# Residual Risks
- Any strict-mode acceptance of invalid cross-file graph is a hard no-go blocker.
- Missing visual evidence artifact matrix coverage blocks closeout.

# Training Demonstration Evidence
- Project ID: `multi_plane_layout`
- Run command(s):
  - `uv run pytest tests -k "planes_schema_validation or planes_cross_file_invariants" -q`
- Deterministic artifact references:
  - `artifacts/debug_menu/r040_smoke/manifest.json`
  - `artifacts/debug_menu/r040_smoke/runtime/manifest.json`
- Demo scope verdicts:
  - split-file planes layout: `pending`
  - strict validator + cross-file invariants: `pending`
- Training go blocker evaluation:
  - blocker: `strict mode accepts invalid cross-file graph`
  - status: `pending`
