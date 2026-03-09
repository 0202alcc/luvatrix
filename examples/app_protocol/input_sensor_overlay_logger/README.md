# input_sensor_overlay_logger

## Objective
Log input overlay actions and sensor snapshots into an in-app event ledger.

## Concepts introduced
- Input event logging
- Overlay + sensor co-visualization
- Stable event ledger output

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `log_input` from the on-screen control.
- Trigger `refresh_sensors` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/app_protocol/input_sensor_overlay_logger/validation_artifact.json` with:
- `input_logged` == `True`
- `sensor_refresh_count` == `1`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/app_protocol/input_sensor_overlay_logger/app_main.py --validate`

## Deterministic validation artifact reference
`examples/app_protocol/input_sensor_overlay_logger/validation_artifact.json`
