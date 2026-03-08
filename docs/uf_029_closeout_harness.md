# UF-029 Closeout Harness

## Scope
Milestone `UF-029` validates the Planes v2 compiler path for canonical IR parity between split-file input and monolith adapter input.

## Training Mapping
- `closeout_training_project_ids`: `camera_overlay_basics`

## Demo Scope
1. Split vs monolith compile parity to canonical IR.
2. Overlay parity semantics.

## Go Blockers
- Canonical IR parity mismatch on ordering.
- Canonical IR parity mismatch on transforms.
- Canonical IR parity mismatch on hit-test semantics.

## Command Profile
1. `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest tests -k "planes_split_compile or planes_parity_equivalence or planes_ir_contract" -q`
2. `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q`
3. `UV_CACHE_DIR=.uv-cache PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`

## Deterministic Artifacts
- `artifacts/uf029/parity_digest.json`
- `artifacts/uf029/compiler_contract_summary.json`

## GO Rubric
- `compile_correctness`: 0-100
- `parity_equivalence`: 0-100
- `error_diagnostics`: 0-100
- score formula: `0.45*compile_correctness + 0.35*parity_equivalence + 0.2*error_diagnostics`
- GO threshold: `>= 86`
