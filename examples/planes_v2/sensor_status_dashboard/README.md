# sensor_status_dashboard

## Objective
Refresh synthetic sensor status cards and show deterministic dashboard telemetry.

## Concepts introduced
- Sensor dashboard card updates
- Refresh command handlers
- Deterministic telemetry ticks

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `refresh_sensors` from the on-screen control.
- Trigger `refresh_sensors` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/planes_v2/sensor_status_dashboard/validation_artifact.json` with:
- `sensor_refresh_count` == `2`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/planes_v2/sensor_status_dashboard/app_main.py --validate`

## Deterministic validation artifact reference
`examples/planes_v2/sensor_status_dashboard/validation_artifact.json`
