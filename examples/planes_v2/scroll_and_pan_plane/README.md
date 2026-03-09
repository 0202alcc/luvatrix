# scroll_and_pan_plane

## Objective
Drive viewport scrolling and pan telemetry with scroll events.

## Concepts introduced
- Viewport clipping
- Scroll handlers
- Pan delta accumulation

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `scroll_plane` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/planes_v2/scroll_and_pan_plane/validation_artifact.json` with:
- `scroll_recorded` == `True`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/planes_v2/scroll_and_pan_plane/app_main.py --validate`

## Deterministic validation artifact reference
`examples/planes_v2/scroll_and_pan_plane/validation_artifact.json`
