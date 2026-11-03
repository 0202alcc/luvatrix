# planes_v2_poc_plus

## Objective
Record `/home`, `/settings`, and `/analytics` path strings in app state. Those strings are telemetry. They do not change the compiled route or `active_plane_ids`. Route ids in `plane.json` are `home`, `settings`, and `analytics`.

## Concepts introduced
- Route path strings stored in app state
- Navigation telemetry for validation artifacts

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `route_home` from the on-screen control.
- Trigger `route_settings` from the on-screen control.
- Trigger `route_analytics` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/planes_v2/planes_v2_poc_plus/validation_artifact.json` with:
- `active_route_path` == `/analytics`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/planes_v2/planes_v2_poc_plus/app_main.py --validate`

## Deterministic validation artifact reference
`examples/planes_v2/planes_v2_poc_plus/validation_artifact.json`
