# multi_plane_layout

## Objective
Switch focus across primary and secondary planes in a multi-plane route.

## Concepts introduced
- Planes v2 multi-plane layout
- Plane focus controls
- Route active-plane behavior

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `activate_plane_primary` from the on-screen control.
- Trigger `activate_plane_secondary` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/app_protocol/multi_plane_layout/validation_artifact.json` with:
- `plane_switch_count` == `2`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/app_protocol/multi_plane_layout/app_main.py --validate`

## Deterministic validation artifact reference
`examples/app_protocol/multi_plane_layout/validation_artifact.json`
