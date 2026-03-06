# Frame-Step + Perf HUD Contract (T-2908)

## Scope
Define deterministic frame-step control and perf HUD snapshot contract behavior for macOS-first debugging.

## Frame-Step Contract
1. Frame-step is valid only while paused.
2. A single frame-step increments `frame_index` by one.
3. Frame-step updates and persists `last_ordering_digest` for determinism verification.

## Perf HUD Snapshot Fields
1. `frame_index`
2. `frame_time_ms`
3. `fps`
4. `present_mode`
5. `ordering_digest`

## Platform Capability Policy
1. `macos`: supports `debug.frame.step` and `debug.perf.hud`.
2. `windows`: explicit `debug.frame.step.stub` and `debug.perf.hud.stub` declarations only.
3. `linux`: explicit `debug.frame.step.stub` and `debug.perf.hud.stub` declarations only.
