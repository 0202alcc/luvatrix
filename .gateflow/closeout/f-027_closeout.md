# Objective Summary
- F-027 finalized the Planes v2 foundation contract: split-file layout, canonical basis alias policy, deterministic ordering rules, and milestone CI/failure procedures.
- Deliverables are captured in `docs/planes_v2_protocol_foundation.md` and `ops/planning/specs/f-027_ci_profile_and_failure_procedure.md`.

# Task Final States
- `T-3400` `[CLOSEOUT HARNESS] Define Planes v2 closeout metric and evidence harness` -> `Done` (closed with GO note).
- `T-3401` `Freeze Planes v2 protocol/file-system architecture spec` -> `Done` (closed with GO note).
- `T-3402` `Define milestone CI profile and post-merge failure procedure for Planes v2 milestones` -> `Done` (closed with GO note).

# Evidence
- `PYTHONPATH=. uv run pytest tests/test_planes_protocol.py -q` -> `10 passed`.
- `PYTHONPATH=. uv run pytest tests/test_coordinates.py -q` -> `4 passed`.
- `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` -> `validation: PASS`.
- `PYTHONPATH=. uv run pytest tests -k "planes_v2_spec or planes_v2_contract" -q` -> `2 passed, 456 deselected`.
- `PYTHONPATH=. uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q` -> `2 passed, 456 deselected`.
- `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py` -> `all_passed: true` with deterministic action smoke and runtime-prereq-aware skip semantics.

# Determinism
- Canonical basis contract is frozen to `u_basis/v_basis/w_basis`; aliases `x/y/z` and `i_hat/j_hat/k_hat` are normalization-only inputs.
- Plane depth rules are explicit: camera plane fixed at `k_hat_index == 0`; world planes strictly `< 0`.
- Deterministic ordering is fixed as `k_hat_index`, then `z_local`, then `mount_order`, then lexical `component_id`.

# Protocol Compatibility
- Backward-compatibility boundary preserves alias inputs while runtime evaluates canonical fields only.
- Existing app behavior remains compatible by normalization prior to runtime ordering and placement.
- Default frame policy explicitly includes `screen_tl`, `cartesian_bl`, and `cartesian_center`.

# Modularity
- Protocol foundation and CI/failure policy are authored as separate artifacts so downstream milestones can consume them independently:
  - `docs/planes_v2_protocol_foundation.md`
  - `ops/planning/specs/f-027_ci_profile_and_failure_procedure.md`
- Gate checks are isolated into selector-targeted tests:
  - `tests/test_planes_v2_spec_contract_gate.py`
  - `tests/test_planes_v2_debug_bundle_gate.py`

# Residual Risks
- macOS runtime smoke can be environment-constrained when Vulkan Python bindings are unavailable; harness now reports deterministic skip-with-reason semantics.
- Full macOS run-app validation still depends on host runtime prerequisites beyond protocol/spec artifacts.

# Training Demonstration Evidence
- Project ID: `hello_plane`
  - Run command(s): `PYTHONPATH=. uv run pytest tests/test_planes_protocol.py -q`
  - Deterministic artifact references: `artifacts/f027_training/hello_plane_pytest.txt`
  - Demo scope verdicts:
    - minimal plane/component app contract: `PASS`
    - all predefined coordinate frames (`screen_tl`, `cartesian_bl`, `cartesian_center`): `PASS`
    - canonical alias mapping (`x/y/z` and `i_hat/j_hat/k_hat`): `PASS`
- Project ID: `coordinate_playground`
  - Run command(s): `PYTHONPATH=. uv run pytest tests/test_coordinates.py -q`
  - Deterministic artifact references: `artifacts/f027_training/coordinate_playground_pytest.txt`
  - Demo scope verdicts:
    - minimal plane/component app contract: `PASS`
    - all predefined coordinate frames (`screen_tl`, `cartesian_bl`, `cartesian_center`): `PASS`
    - canonical alias mapping (`x/y/z` and `i_hat/j_hat/k_hat`): `PASS`
- Training Go blockers evaluation:
  - coordinate ambiguity: `CLEAR` (canonical-basis-only runtime contract + passing protocol tests)
  - non-deterministic coordinate placement: `CLEAR` (deterministic ordering rules + passing coordinate tests)
