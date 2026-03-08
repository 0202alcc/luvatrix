# M028 Execution Board (F-028)

Milestone: **F-028**  
Name: **Planes v2 Schema + Cross-File Validator Layer**

## GateFlow Columns

### Intake
- `T-3403` Implement schema validation pipeline for Planes v2 split files
- `T-3404` Implement cross-file invariant validator for manifest/plane/route/frame references
- `T-3405` Define strict vs permissive mode policy and diagnostics contract
- `T-3426` Define Planes v2 visual evidence schema + manifest contract
- `T-3427` Add validator checks for required visual evidence artifacts

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
- `T-3420` [CLOSEOUT HARNESS] Define F-028 validator closeout metric and evidence harness

### Blocked
- _None_

## Evidence Commands

- `uv run pytest tests -k "planes_schema_validation or planes_cross_file_invariants" -q`
- `uv run --with pytest pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q`
- `PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
- `uv run python ops/planning/agile/validate_milestone_task_links.py`
- `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate links`
- `uvx gateflow --root /Users/aleccandidato/Projects/luvatrix validate closeout`
