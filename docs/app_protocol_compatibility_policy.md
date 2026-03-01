# App Protocol Compatibility Policy

This policy defines version compatibility, deprecation lifecycle, and migration requirements for first-party Luvatrix apps.

## 1. Protocol Support Matrix

Current runtime policy:

| Runtime date | Runtime protocol version | Supported manifest protocol versions | Deprecated but accepted |
| --- | --- | --- | --- |
| 2026-03-01 | `1` | `1` | none |

Interpretation:

1. `protocol_version = "1"` is accepted.
2. Any other manifest protocol version is rejected.
3. There are currently no deprecated-but-still-accepted versions.

## 2. Runtime Bounds Behavior (`min`/`max`)

App manifests may set:

1. `min_runtime_protocol_version`
2. `max_runtime_protocol_version`

Current runtime uses protocol `1` and applies checks in this order:

1. reject if `manifest.protocol_version` is unsupported
2. reject if runtime version is below `min_runtime_protocol_version`
3. reject if runtime version is above `max_runtime_protocol_version`
4. allow and warn only when version is accepted but marked deprecated

Examples:

```toml
# accepted on runtime protocol 1
protocol_version = "1"
min_runtime_protocol_version = "1"
max_runtime_protocol_version = "1"
```

```toml
# rejected on runtime protocol 1 (runtime below app minimum)
protocol_version = "1"
min_runtime_protocol_version = "2"
```

```toml
# rejected on runtime protocol 1 (runtime above app maximum)
protocol_version = "1"
max_runtime_protocol_version = "0"
```

## 3. Deprecation Lifecycle Policy

For future protocol revisions, use this lifecycle:

1. `Announce`: publish target removal and migration path in docs.
2. `Dual-support`: old version remains accepted but emits warnings.
3. `Default-shift`: examples/templates switch to the newer version.
4. `Removal`: old version is removed from supported set and rejected.

Governance requirements:

1. update compatibility docs and migration guide in the same change
2. add/refresh deterministic tests for acceptance, warnings, and rejection
3. include explicit milestone task evidence before marking release-complete

## 4. Migration Checklist

When bumping a first-party app to a new protocol version:

1. update `protocol_version` in `app.toml`
2. set `min_runtime_protocol_version` and `max_runtime_protocol_version` bounds intentionally
3. validate capabilities still map to supported names and semantics
4. run compatibility and app runtime tests
5. run app smoke command for representative runtime path
6. update app-level docs and runbook links

## 5. Migration Example

Before:

```toml
protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = ["sensor.thermal"]
```

After (same runtime target, explicit bounds):

```toml
protocol_version = "1"
min_runtime_protocol_version = "1"
max_runtime_protocol_version = "1"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = ["sensor.thermal"]
```

## 6. Verification Commands

Compatibility and bounds checks:

```bash
uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py -k "protocol or runtime_protocol"
```

Runtime integration coverage:

```bash
uv run pytest tests/test_unified_runtime.py tests/test_app_runtime.py
```
