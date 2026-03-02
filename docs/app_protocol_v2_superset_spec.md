# App Protocol v2 Superset Spec

Status: Draft

This spec defines protocol v2 as a superset of v1.

## Compatibility Contract

1. Runtime MUST continue accepting `protocol_version = "1"` manifests.
2. Runtime MUST accept `protocol_version = "2"` manifests.
3. v1 apps run through `runtime.kind = "python_inproc"` behavior (default).
4. v2 apps may run through `runtime.kind = "process"` over `stdio_jsonl`.

## Manifest Additions (v2)

Optional `[runtime]` table:

```toml
[runtime]
kind = "python_inproc" # or "process"
transport = "stdio_jsonl"
command = ["python", "-u", "worker.py"]
```

Rules:

1. default `kind` is `python_inproc`.
2. default `transport` is `stdio_jsonl`.
3. `kind = "process"` requires non-empty `command`.

## Planes Capability and Version Signaling (M-008 extension)

Optional `[planes]` table (recommended for protocol v2 apps using Planes):

```toml
[planes]
schema_version = "0.2.0-dev"
min_schema_version = "0.1.0"
max_schema_version = "0.2.0-dev"
required_features = ["multi_plane", "camera_overlay", "blend.delta_rgba"]
optional_features = ["section_cuts", "route_activation", "perf.culling_hints"]
```

### Rules

1. If `[planes]` is omitted, runtime assumes legacy Planes compatibility behavior.
2. `schema_version` declares the app-authored schema target.
3. Runtime MUST reject if active schema support is below `min_schema_version`.
4. Runtime MUST reject if active schema support is above `max_schema_version`.
5. Every item in `required_features` MUST be supported, otherwise fail startup.
6. `optional_features` MAY be silently unavailable, but runtime SHOULD expose availability in diagnostics.

### Feature Namespace (current draft)

1. `multi_plane`
2. `camera_overlay`
3. `section_cuts`
4. `blend.absolute_rgba`
5. `blend.delta_rgba`
6. `route_activation`
7. `perf.culling_hints`

### Backward Compatibility Mapping

For v0 Planes payloads under protocol v2:

1. Treat single `plane` as implicit `planes=[...]`.
2. Map legacy `z_index` to local ordering in compatibility mode.
3. Assume `blend.absolute_rgba` unless explicit override exists.
4. Treat overlay-like components via compatibility shim when no explicit `attachment_kind` exists.

## Process Lane Wire Contract (Python-first)

Transport: newline-delimited JSON messages on stdin/stdout.

Host -> app:

1. `host.hello`
2. `host.tick`
3. `host.stop`

App -> host:

1. `app.init_ok`
2. `app.commands`
3. `app.stop_ok`

### Supported v2 command ops (current)

1. `solid_fill`: fills full matrix with one RGBA value.

Example app response:

```json
{"type":"app.commands","ops":[{"op":"solid_fill","rgba":[12,34,56,255]}]}
```

## Adapter Model

1. `python_inproc`: existing lifecycle adapter (`init/loop/stop`) in same process.
2. `process`: host-managed subprocess lifecycle bridge with protocol validation.

## Governance Notes

1. `CURRENT_PROTOCOL_VERSION = "2"`.
2. `SUPPORTED_PROTOCOL_VERSIONS = {"1", "2"}`.
3. Protocol `1` is accepted with deprecation warning.
4. Planes capability/version checks are enforced only when `[planes]` metadata is present.
