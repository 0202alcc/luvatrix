# M027 Execution Board (F-027)

Milestone: **F-027**  
Name: **Planes v2 Protocol Foundation + File Layout Spec**

## GateFlow Columns

### Intake
- `T-3402` Define milestone CI profile and post-merge failure procedure for Planes v2 milestones

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
- `T-3400` [CLOSEOUT HARNESS] Define Planes v2 closeout metric and evidence harness
- `T-3401` Freeze Planes v2 protocol/file-system architecture spec

### Blocked
- _None_

## Evidence Commands

- `uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q`
- `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
- `uv run python ops/planning/agile/validate_milestone_task_links.py`
- `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate links`
- `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate closeout`
