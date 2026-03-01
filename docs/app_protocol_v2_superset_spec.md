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
