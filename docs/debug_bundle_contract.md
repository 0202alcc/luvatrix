# Debug Bundle Export Contract (T-2909)

## Scope
Define deterministic debug bundle export contract for macOS-first observability evidence packaging.

## Bundle Manifest Fields
1. `bundle_id`
2. `platform`
3. `exported_at_utc`
4. `provenance_id`
5. `artifact_paths`
6. `artifact_classes`

## Required Artifact Classes
1. `captures`
2. `replay`
3. `perf`
4. `provenance`

## Determinism Rule
1. Bundle zip path is deterministic per `bundle_id` (`<output_dir>/<bundle_id>.zip`).
2. Bundle is incomplete if any required artifact class is missing from `artifact_classes`.

## Platform Capability Policy
1. `macos`: supports `debug.bundle.export`.
2. `windows`: explicit `debug.bundle.stub` declaration only.
3. `linux`: explicit `debug.bundle.stub` declaration only.
