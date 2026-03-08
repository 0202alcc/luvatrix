# M030 Execution Board (RF-030)

Milestone: **RF-030**  
Name: **Planes v2 Runtime Integration on Canonical IR**

## GateFlow Columns

### Intake
- `T-3422` [CLOSEOUT HARNESS] Define RF-030 runtime deterministic closeout metric and evidence harness
- `T-3410` Integrate runtime to consume canonical IR only
- `T-3411` Enforce deterministic transform/render/hit-test/compositing rules in runtime
- `T-3412` Normalize device-native orientation to canonical u/v/w before app transforms
- `T-3428` Build planes_v2_poc debug capture harness (macOS-first)

### Success Criteria Spec
- _None_

### Safety Tests Spec
- _None_

### Implementation Tests Spec
- _None_

### Edge Case Tests Spec
- _None_

### Prototype Stage 1
- _None_

### Prototype Stage 2+
- _None_

### Verification Review
- [ ] Training evidence matrix completed (project id, commands, deterministic artifacts, per-scope verdicts)
- _None_

### Integration Ready
- [ ] Training Go blockers reviewed and clear (or explicitly waived)
- _None_

### Done
- _None_

### Blocked
- _None_

## Evidence Commands

- `uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q`
- `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
- `uv run python ops/planning/agile/validate_milestone_task_links.py`
- `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate links`
- `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate closeout`
