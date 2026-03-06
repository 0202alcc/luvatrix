# Replay Contract (T-2907)

## Scope
Define deterministic input monitor and record/replay contract behavior for macOS-first tooling.

## Replay Manifest Fields
1. `session_id`
2. `seed`
3. `platform`
4. `ordering_digest`
5. `event_count`
6. `recorded_at_utc`

## Determinism Rule
1. Replay event order digest is computed from canonical sequence/timestamp/type/payload fields.
2. Seed-pinned replay is deterministic only when computed digest matches expected digest for the same sequence.

## Platform Capability Policy
1. `macos`: supports replay monitor and replay start capabilities.
2. `windows`: explicit `debug.replay.stub` declaration only.
3. `linux`: explicit `debug.replay.stub` declaration only.
