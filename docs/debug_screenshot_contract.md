# Screenshot Contract (T-2904)

## Scope
Define deterministic screenshot contracts for macOS file and clipboard capture with explicit non-mac stubs.

## Artifact Pairing
1. Screenshot capture emits two artifacts with the same deterministic capture stem:
2. `<capture_id>.png`
3. `<capture_id>.json`
4. Emission contract is atomic: both artifacts exist or neither exists.

## Clipboard Capture Contract
1. `debug.menu.capture.screenshot.clipboard` is macOS-only in this phase.
2. Clipboard capture must not emit screenshot file artifacts.
3. Clipboard capture still records deterministic event metadata (`capture_id`, `captured_at_utc`, `provenance_id`).

## Metadata Sidecar Fields
1. `route`
2. `revision`
3. `captured_at_utc`
4. `provenance_id`
5. `platform`

## Platform Capability Policy
1. `macos`: supported in this phase.
2. `windows`: unsupported stub declarations only, including `debug.capture.screenshot.clipboard.stub`.
3. `linux`: unsupported stub declarations only, including `debug.capture.screenshot.clipboard.stub`.
4. `web`: unsupported stub declarations only, including `debug.capture.screenshot.clipboard.stub`.
