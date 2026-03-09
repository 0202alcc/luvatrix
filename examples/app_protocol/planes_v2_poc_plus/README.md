# planes_v2_poc_plus

## Objective
Package Planes v2 PoC+ training shell with route-oriented structure hints for /home, /settings, /analytics.

## Concepts introduced
- Route-aware app packaging\n- Modular expansion points\n- Deterministic closeout evidence

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
- `examples/app_protocol/planes_v2_poc_plus/validation_artifact.json` with deterministic fingerprint.

## Validation checklist
- [ ] `app.toml` exists and points to `app_main:create`.
- [ ] Validation command exits with code `0`.
- [ ] Artifact file exists and contains `"status": "PASS"`.
- [ ] Artifact fingerprint is stable across repeated runs.

## Stretch challenge
Wire this app into a richer runtime flow by replacing `create()` stub state with live plane/component behavior while preserving deterministic validation output.

## Runnable command
`PYTHONPATH=. uv run python examples/app_protocol/planes_v2_poc_plus/app_main.py --validate`

## Deterministic validation artifact reference
`examples/app_protocol/planes_v2_poc_plus/validation_artifact.json`
