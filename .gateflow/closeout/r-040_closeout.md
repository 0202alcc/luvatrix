# R-040 Closeout Packet

## Objective Summary
- Converted macOS debug menu actions from stub handler events to functional runtime handlers for screenshot, recording, overlays, replay, frame-step, perf HUD, and debug bundle export.
- Preserved crash-safe dispatch behavior through `DebugMenuDispatcher` fallback semantics and explicit action-disable states.
- Added functional kill-switch gating via `LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS=0` while keeping existing wiring rollback path.

## Task Final States
- `T-3300` Done
- `T-3301` Done
- `T-3302` Done
- `T-3303` Done
- `T-3304` Done
- `T-3305` Done
- `T-3306` Done
- `T-3307` Done
- `T-3308` Done
- `T-3309` Done
- `T-3310` Done

## Evidence
- `docs/debug_menu_functional_harness.md`
- `ops/ci/r040_macos_debug_menu_functional_smoke.py`
- `artifacts/debug_menu/r040_smoke/manifest.json`
- `artifacts/debug_menu/r040_smoke/runtime/*`
- `ops/planning/agile/m040_execution_board.md`

## Determinism
- Replay ordering digest is derived from canonical replay events and persisted in replay manifests.
- Frame-step advances only from paused replay state and records deterministic digest continuity.
- Bundle export manifest carries deterministic artifact classes (`captures`, `replay`, `perf`, `provenance`) with stable class names and manifest schema.

## Protocol Compatibility
- Existing debug policy defaults are preserved (`enable_default_debug_root=true` unless explicitly disabled through manifest policy).
- Existing rollback path (`LUVATRIX_MACOS_DEBUG_MENU_WIRING=0`) remains deterministic `DISABLED`.
- Added functional gating path does not alter app protocol compatibility defaults.

## Modularity
- Runtime action handlers are encapsulated in `MoltenVKMacOSBackend` and continue to use shared contracts from `luvatrix_core/core/debug_capture.py`.
- Smoke verification is isolated in `ops/ci/r040_macos_debug_menu_functional_smoke.py`.

## Residual Risks
- Live run-app macOS checks depend on local AppKit/PyObjC availability; missing runtime deps force No-Go despite test-level pass.
- Runtime action menu-item enablement is computed at config/dispatch time and may require future live-menu refresh hooks for mid-session UX parity.
