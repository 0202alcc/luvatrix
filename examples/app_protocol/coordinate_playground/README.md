# coordinate_playground

## Objective
Practice coordinate-space focused app packaging and reproducible artifact generation.

## Concepts introduced
- Coordinate frame literacy\n- Deterministic command execution\n- Artifact schema consistency

## Files to inspect
- `app.toml`
- `app_main.py`
- `validation_artifact.json` (generated)

## Hands-on tasks
1. Run the validation command.
2. Inspect `validation_artifact.json` and verify `status` is `PASS`.
3. Re-run the command and confirm artifact content is deterministic.

## Expected outputs/artifacts
- Console line starting with `VALIDATION_ARTIFACT=`.
- `examples/app_protocol/coordinate_playground/validation_artifact.json` with deterministic fingerprint.

## Validation checklist
- [ ] `app.toml` exists and points to `app_main:create`.
- [ ] Validation command exits with code `0`.
- [ ] Artifact file exists and contains `"status": "PASS"`.
- [ ] Artifact fingerprint is stable across repeated runs.

## Stretch challenge
Wire this app into a richer runtime flow by replacing `create()` stub state with live plane/component behavior while preserving deterministic validation output.

## Runnable command
`PYTHONPATH=. uv run python examples/app_protocol/coordinate_playground/app_main.py --validate`

## Deterministic validation artifact reference
`examples/app_protocol/coordinate_playground/validation_artifact.json`
