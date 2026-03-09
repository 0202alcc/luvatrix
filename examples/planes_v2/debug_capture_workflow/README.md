# debug_capture_workflow

## Objective
Execute full debug capture workflow controls (screenshot, record, replay, frame-step, perf-hud, bundle).

## Concepts introduced
- Debug capture lifecycle
- Record/replay toggles
- Bundle export readiness

## Files to inspect
- `app.toml`
- `app_main.py`
- `plane.json`
- `assets/`
- `validation_artifact.json` (generated)

## Hands-on tasks
- Trigger `debug_screenshot` from the on-screen control.
- Trigger `debug_record` from the on-screen control.
- Trigger `debug_replay` from the on-screen control.
- Trigger `debug_frame_step` from the on-screen control.
- Trigger `debug_perf_hud` from the on-screen control.
- Trigger `debug_bundle` from the on-screen control.
- Run the validation command.
- Open the resulting artifact and verify every interactive check is `true`.

## Expected outputs/artifacts
- Console output containing `VALIDATION_ARTIFACT=`.
- `examples/planes_v2/debug_capture_workflow/validation_artifact.json` with:
- `bundle_exported` == `True`
- `frame_step_count` == `1`
- `perf_hud_toggled` == `True`
- `record_toggled` == `True`
- `replay_started` == `True`
- `screenshot_taken` == `True`

## Validation checklist
- [ ] App loads through `app_main:create`.
- [ ] Interaction handlers execute without runtime errors.
- [ ] `interactive_checks` in artifact are all `true`.
- [ ] Deterministic fingerprint remains stable across repeated runs.

## Stretch challenge
Add an additional interaction control and extend `training_protocol.py` validation checks while preserving deterministic artifact output.

## Runnable command
`PYTHONPATH=. uv run python examples/planes_v2/debug_capture_workflow/app_main.py --validate`

## Deterministic validation artifact reference
`examples/planes_v2/debug_capture_workflow/validation_artifact.json`
