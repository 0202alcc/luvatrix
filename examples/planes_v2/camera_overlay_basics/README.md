# camera_overlay_basics

## Objective
Toggle camera overlay HUD visibility while maintaining world-plane content.

## Concepts introduced
- Camera overlay attachment
- Overlay state toggles
- Independent overlay rendering

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `toggle_overlay` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/planes_v2/camera_overlay_basics/validation_artifact.json` with:
- `overlay_toggled` == `True`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/planes_v2/camera_overlay_basics/app_main.py --validate`

## Deterministic validation artifact reference
`examples/planes_v2/camera_overlay_basics/validation_artifact.json`
