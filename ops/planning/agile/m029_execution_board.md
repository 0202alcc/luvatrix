# M029 Execution Board (UF-029)

Milestone: **UF-029**  
Name: **Planes v2 Compiler to Canonical IR + Parity Contract**

## GateFlow Columns

### Intake
- `T-3421` [CLOSEOUT HARNESS] Define UF-029 compiler/parity closeout metric and evidence harness
- `T-3406` Define canonical IR mapping contract for split files and monolith adapter
- `T-3407` Implement split-file compiler path to canonical Planes IR
- `T-3408` Implement monolith compatibility adapter to canonical Planes IR
- `T-3409` Implement parity suite for monolith vs split canonical equivalence

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
- _None_

### Integration Ready
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
