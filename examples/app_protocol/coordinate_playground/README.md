# coordinate_playground

## Objective
Capture pointer coordinates and store the latest sampled click location.

## Concepts introduced
- Pointer event routing
- Coordinate capture
- State-to-UI feedback loop

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `capture_coordinates` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/app_protocol/coordinate_playground/validation_artifact.json` with:
- `captured_coordinates_set` == `True`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/app_protocol/coordinate_playground/app_main.py --validate`

## Deterministic validation artifact reference
`examples/app_protocol/coordinate_playground/validation_artifact.json`
