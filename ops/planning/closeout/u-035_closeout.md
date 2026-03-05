# U-035 Closeout

## Objective Summary
- Delivered macOS-first visual/capture tooling contracts for screenshot metadata sidecars, recording lifecycle artifacts, and overlay behavior.
- Enforced explicit non-mac stub/capability declarations for Windows/Linux to avoid undefined platform behavior in this phase.
- Evaluated Go/No-Go in macOS context only with explicit reopen intent for multi-platform expansion.

## Task Final States
- `T-2921` Done: visual/capture closeout metric and evidence harness documented.
- `T-2904` Done: screenshot tool contract with deterministic sidecar schema and atomic pairing semantics.
- `T-2905` Done: recording artifact contract with budget envelope checks for start/stop/steady overhead.
- `T-2906` Done: overlay tooling contract with bounds/dirty-rect/coordinate model and non-destructive toggle semantics.

## Evidence
- `PYTHONPATH=. uv run pytest tests -k "debug_screenshot or debug_recording or debug_overlay" -q` -> `7 passed`.
- `PYTHONPATH=. uv run python ops/planning/agile/validate_milestone_task_links.py` -> `validation: PASS`.
- `PYTHONPATH=. uv run python ops/planning/api/validate_closeout_packet.py --milestone-id U-035` -> `closeout packet: PASS`.
- Evidence docs:
  - `docs/debug_visual_capture_harness.md`
  - `docs/debug_screenshot_contract.md`
  - `docs/debug_recording_contract.md`
  - `docs/debug_overlay_contract.md`

## Determinism
- Screenshot artifact generation is deterministic from `capture_id` and includes required provenance fields.
- Recording manifests are schema-validated and budget results are deterministic for fixed inputs.
- Overlay toggles preserve content digest before/after toggle and report non-destructive outcomes by contract.

## Protocol Compatibility
- Capability IDs remain canonical and extend prior debug-menu foundation without breaking existing contracts.
- macOS support is explicit for capture/overlay capabilities; Windows/Linux are explicit stubs with unsupported reasons.

## Modularity
- Visual/capture contracts are isolated in `luvatrix_core.core.debug_capture`.
- Menu capability wiring remains in `luvatrix_core.core.debug_menu`.
- Contract behavior is exposed via pure-data models and validators with focused tests.

## Residual Risks
- This phase does not implement native Windows/Linux adapters; those paths remain stubs and require follow-up implementation/testing.
- Runtime capture overhead baselines are contract-level in this phase; expanded platform perf characterization is required on reopen.
