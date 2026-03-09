# hello_plane

## Objective
Render a starter plane app and toggle themes through direct click interaction.

## Concepts introduced
- Plane runtime bootstrapping
- Theme toggle event handling
- Deterministic state snapshots

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `toggle_theme` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/app_protocol/hello_plane/validation_artifact.json` with:
- `theme_toggled` == `True`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/app_protocol/hello_plane/app_main.py --validate`

## Deterministic validation artifact reference
`examples/app_protocol/hello_plane/validation_artifact.json`
