# App Protocol v1 -> v2 Migration Guide

## Goal

Move apps to protocol v2 without breaking v1 support.

## Path

1. Keep existing v1 app manifest and lifecycle working.
2. Add v2 fields incrementally.
3. Optionally migrate to process runtime lane.

## Step 1: Keep current in-process mode

```toml
protocol_version = "2"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []

[runtime]
kind = "python_inproc"
```

## Step 2: Move to Python process lane

```toml
protocol_version = "2"
entrypoint = "app_main:create"
required_capabilities = ["window.write"]
optional_capabilities = []

[runtime]
kind = "process"
transport = "stdio_jsonl"
command = ["python", "-u", "worker.py"]
```

## Step 3: Implement worker interface

Worker must handle:

1. `host.hello` -> respond `app.init_ok`
2. `host.tick` -> respond `app.commands`
3. `host.stop` -> respond `app.stop_ok`

Reference SDK:

- `luvatrix_core/core/process_sdk.py`

## Verification

```bash
PYTHONPATH=. uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py
```
