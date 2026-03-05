# Screenshot Contract (T-2904)

## Scope
Define a deterministic screenshot artifact contract for macOS with explicit non-mac stubs.

## Artifact Pairing
1. Screenshot capture emits two artifacts with the same deterministic capture stem:
2. `<capture_id>.png`
3. `<capture_id>.json`
4. Emission contract is atomic: both artifacts exist or neither exists.

## Metadata Sidecar Fields
1. `route`
2. `revision`
3. `captured_at_utc`
4. `provenance_id`
5. `platform`

## Platform Capability Policy
1. `macos`: supported in this phase.
2. `windows`: unsupported stub declarations only.
3. `linux`: unsupported stub declarations only.
