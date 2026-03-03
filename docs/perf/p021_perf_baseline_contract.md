# P-021 Deterministic Performance Baseline + Gate Contract

Date: `2026-03-03`  
Milestone: `P-021`  
Tasks: `T-2101`, `T-2102`, `T-2103`, `T-2104`

## 1) Frame Copy Chain Map (`T-2101`)

Per-frame byte ownership handoff and copy stages:

1. `AppContext.finalize_ui_frame` (`luvatrix_core/core/app_runtime.py`)
- Ownership boundary: UI renderer output -> WindowMatrix write payload.
- Copy stage:
  - partial compose: each dirty rect uses `frame[y:y+h, x:x+w, :].clone()`.
  - full compose: full frame tensor forwarded as `FullRewrite`.
- Telemetry: `copy_count`, `copy_bytes`, `ui_pack_ns`.

2. `WindowMatrix.submit_write_batch` (`luvatrix_core/core/window_matrix.py`)
- Ownership boundary: previous matrix revision -> staged mutable working tensor.
- Copy stage: `staged = self._matrix.clone()`.
- Telemetry: `matrix_stage_clone_ns`, `copy_count`, `copy_bytes`.

3. `DisplayRuntime.run_once` (`luvatrix_core/core/display_runtime.py`)
- Ownership boundary: committed WindowMatrix revision -> render-target frame snapshot.
- Copy stage: `snapshot = self._matrix.read_snapshot()` (`clone()` under write lock).
- Telemetry: `matrix_snapshot_clone_ns`, `copy_count`, `copy_bytes`.

4. `MoltenVKMacOSBackend._upload_rgba_to_staging` (`luvatrix_core/platform/macos/vulkan_backend.py`)
- Ownership boundary: CPU RGBA tensor -> mapped Vulkan staging memory.
- Copy stages:
  - `pack`: `clipped.cpu().numpy().tobytes(order="C")`.
  - `map`: `vkMapMemory`.
  - `memcpy`: `ffi.memmove` or `ctypes.memmove`.
- Telemetry: `upload_pack_ns`, `upload_map_ns`, `upload_memcpy_ns`, `copy_count`, `copy_bytes`.

Nominal byte formula per full-frame stage: `width * height * 4`.

## 2) Telemetry Contract (`T-2102`)

Runtime perf payload now includes:

1. `copy_count` (int)
2. `copy_bytes` (int)
3. `copy_timing_ms.ui_pack`
4. `copy_timing_ms.matrix_stage_clone`
5. `copy_timing_ms.matrix_snapshot_clone`
6. `copy_timing_ms.upload_pack`
7. `copy_timing_ms.upload_map`
8. `copy_timing_ms.upload_memcpy`

All fields are deterministic and non-negative.

## 3) Scenario Harness (`T-2103`)

Harness entrypoint: `tools/perf/run_suite.py`.

Scenarios:

1. `idle`
2. `scroll`
3. `drag`
4. `resize_stress`

Additional scenario:

1. `render_copy_chain` for copy-path-focused baseline snapshots.

Outputs:

1. `artifacts/perf/render_copy_baseline.json`
2. `artifacts/perf/interactive_baseline.json`

Each scenario executes two deterministic trials; the suite marks `deterministic=false` on replay mismatches.

## 4) CI Gate Contract (`T-2104`)

Contract file: `tools/perf/baseline_contract.json`.

Gate evaluator: `tools/perf/assert_thresholds.py`.

Fail conditions:

1. deterministic replay mismatch for any scenario.
2. `p95_frame_total_ms` exceeds contract.
3. `jitter_ms` exceeds contract.
4. `p95_copy_bytes` exceeds contract.
5. `p95_copy_count` exceeds contract.
6. `p95_copy_pack_ms` / `p95_copy_map_ms` / `p95_copy_memcpy_ms` exceed contract.

Recommended CI sequence:

1. `PYTHONPATH=. uv run python tools/perf/run_suite.py --scenario all_interactive --out artifacts/perf/interactive_baseline.json`
2. `PYTHONPATH=. uv run python tools/perf/assert_thresholds.py --suite baseline_contract --baseline artifacts/perf/interactive_baseline.json`
