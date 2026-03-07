# macOS Debug Menu Runtime Wiring (R-039)

## Runtime Wiring
- `UnifiedRuntime.run_app` resolves `debug_policy` from app manifest and forwards the policy profile to macOS-capable render targets.
- `VulkanTarget` and `MacOSVulkanPresenter` expose `configure_debug_menu(...)` so policy wiring is injected before app loop ticks.
- `MoltenVKMacOSBackend` builds AppKit Debug menu items from canonical `debug.menu.*` IDs and dispatches through the crash-safe dispatcher.

## Rollback Control
- Set `LUVATRIX_MACOS_DEBUG_MENU_WIRING=0` to disable runtime debug menu action wiring.
- With rollback enabled, debug menu actions remain present but dispatch returns deterministic `DISABLED` status and emits warning/event lines.

## Deterministic Evidence
- Runtime wiring writes:
  - `artifacts/debug_menu/runtime/manifest.json`
  - `artifacts/debug_menu/runtime/events.jsonl`
- E2E smoke harness:
  - `PYTHONPATH=. uv run python ops/ci/r039_macos_menu_smoke.py`
  - Outputs `artifacts/debug_menu/r039_smoke/manifest.json` and per-app logs.
