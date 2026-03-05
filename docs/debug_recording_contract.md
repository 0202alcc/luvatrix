# Recording Contract (T-2905)

## Scope
Define deterministic recording lifecycle artifacts and budget safety checks for macOS-first tooling.

## Artifact Manifest Fields
1. `session_id`
2. `route`
3. `revision`
4. `started_at_utc`
5. `stopped_at_utc`
6. `provenance_id`
7. `frame_count`
8. `platform`

## Budget Envelope
1. Start transition overhead (`start_overhead_ms`)
2. Stop transition overhead (`stop_overhead_ms`)
3. Steady recording overhead (`steady_overhead_ms`)
4. Any overrun is a budget failure.

## Platform Capability Policy
1. `macos`: supported in this phase.
2. `windows`: unsupported stub declarations only.
3. `linux`: unsupported stub declarations only.
