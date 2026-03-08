# M031 Execution Board (F-031)

Milestone: **F-031**  
Name: **Planes v2 Backward-Compat Adapter + Migration Tooling**

## GateFlow Columns

### Intake
- `T-3423` [CLOSEOUT HARNESS] Define F-031 compatibility/migration closeout metric and evidence harness
- `T-3413` Add version-gated v2 entry path while preserving existing app-facing APIs
- `T-3414` Maintain z_index_alias compatibility while canonicalizing on k_hat_index ordering
- `T-3415` Deliver legacy app conformance suite under adapter path

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
