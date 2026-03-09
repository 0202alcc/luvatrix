# Objective Summary
- RF-030 delivered runtime integration on canonical Planes IR with deterministic interaction ordering.
- Runtime ingest path is constrained to canonical IR structures; no non-canonical direct runtime bypass is used.
- Deterministic draw/hit-test/compositing semantics and backend orientation normalization remained stable under RF-030 validation evidence.

# Task Final States
- `T-3422` Done (closeout harness defined; controlled close GO recorded).
- `T-3410` Done (canonical IR-only runtime ingestion path validated; controlled close GO recorded).
- `T-3411` Done (deterministic transform/render/hit-test/compositing semantics validated; controlled close GO recorded).
- `T-3412` Done (device orientation normalization to canonical `u/v/w` validated; controlled close GO recorded).
- `T-3428` Done (deterministic debug-capture artifact harness emitted for required scenarios; controlled close GO recorded).

# Evidence
- Runtime/protocol/parity test evidence:
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run pytest tests/test_planes_runtime.py tests/test_planes_parity_equivalence.py tests/test_planes_v2_poc_example.py -q` -> `41 passed in 1.56s`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run pytest tests -k "planes_v2 and (debug_screenshot or debug_recording or debug_overlay or debug_replay or debug_frame_step or debug_bundle)" -q` -> `2 passed, 479 deselected in 9.13s`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run pytest tests -k "planes_ir_contract or planes_split_compile or planes_parity_equivalence" -q` -> `8 passed, 473 deselected in 9.14s`
- Functional debug-menu smoke evidence:
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py`
  - Output persisted at `artifacts/rf030/deterministic_capture/debug_menu_smoke.json`.
- Deterministic scenario artifact pack (T-3428):
  - `artifacts/rf030/deterministic_capture/startup_idle.json`
  - `artifacts/rf030/deterministic_capture/vertical_scroll.json`
  - `artifacts/rf030/deterministic_capture/horizontal_pan.json`
  - `artifacts/rf030/deterministic_capture/drag_heavy.json`
  - `artifacts/rf030/deterministic_capture/resize_burst.json`
  - `artifacts/rf030/deterministic_capture/artifact_manifest.json`

# Determinism
- Required RF-030 scenarios are recorded with deterministic flags in `artifacts/rf030/deterministic_capture/artifact_manifest.json`.
- Overlay toggle and replay/frame-step execution evidence are captured from debug-menu functional smoke with deterministic pass status.
- No RF-030 hard no-go condition was observed:
  - no transform/render/hit-test ordering mismatch,
  - no canonical IR bypass path evidence.

# Protocol Compatibility
- RF-030 remains aligned with canonical Planes IR ordering and basis contracts (`k_hat_index`, `z_local`, `mount_order`, `u/v/w`).
- Runtime behavior remains compatible with existing debug/capture contract tests and deterministic replay/frame-step expectations.

# Modularity
- Milestone evidence and artifacts are isolated under `artifacts/rf030/deterministic_capture/` and `.gateflow/closeout/rf-030_closeout.md`.
- Planning lifecycle/state transitions were performed through GateFlow CLI only against canonical `.gateflow/*` records.

# Residual Risks
- macOS runtime execution remains environment-dependent in smoke preflight (`missing_runtime_prereqs` skip path may appear on hosts lacking runtime prerequisites).
- Continued CI enforcement on main remains required to prevent regressions in deterministic ordering or canonical ingest constraints.

# Training Demonstration Evidence
- `closeout_training_project_ids`: `scroll_and_pan_plane`, `interactive_components`
- Run command(s):
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run python tools/perf/run_suite.py --scenario idle --samples 120 --width 1280 --height 720 --seed 1337 --out artifacts/rf030/deterministic_capture/startup_idle.json`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run python tools/perf/run_suite.py --scenario scroll --samples 120 --width 1280 --height 720 --seed 1337 --out artifacts/rf030/deterministic_capture/vertical_scroll.json`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run python tools/perf/run_suite.py --scenario horizontal_pan --samples 120 --width 1280 --height 720 --seed 1337 --out artifacts/rf030/deterministic_capture/horizontal_pan.json`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run python tools/perf/run_suite.py --scenario drag_heavy --samples 120 --width 1280 --height 720 --seed 1337 --out artifacts/rf030/deterministic_capture/drag_heavy.json`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache uv run python tools/perf/run_suite.py --scenario resize_overlap_incremental_required --samples 120 --width 1280 --height 720 --seed 1337 --out artifacts/rf030/deterministic_capture/resize_burst.json`
  - `UV_CACHE_DIR=/Users/aleccandidato/Projects/luvatrix/.uv-cache PYTHONPATH=. uv run python ops/ci/r040_macos_debug_menu_functional_smoke.py > artifacts/rf030/deterministic_capture/debug_menu_smoke.json`
- Deterministic artifact references:
  - `artifacts/rf030/deterministic_capture/artifact_manifest.json` (scenario digests and deterministic flags)
  - `artifacts/rf030/deterministic_capture/startup_idle.json`
  - `artifacts/rf030/deterministic_capture/vertical_scroll.json`
  - `artifacts/rf030/deterministic_capture/horizontal_pan.json`
  - `artifacts/rf030/deterministic_capture/drag_heavy.json`
  - `artifacts/rf030/deterministic_capture/resize_burst.json`
  - `artifacts/rf030/deterministic_capture/debug_menu_smoke.json`
- Demo scope verdicts:
  - canonical IR-only runtime ingestion: `PASS`
  - deterministic runtime interaction path: `PASS`
