# App Protocol Operator Runbook

Operator procedures for first-party Luvatrix app protocol workloads.

## 1. Command Cookbook

Headless run (baseline):

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render headless --ticks 300
```

macOS render run:

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render macos --width 640 --height 360 --ticks 300
```

Enable macOS sensor providers:

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render headless --sensor-backend macos --ticks 300
```

Audit to SQLite and summarize:

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render headless --ticks 120 --audit-sqlite ./.luvatrix/audit.db
uv run --python 3.14 python main.py audit-report --audit-sqlite ./.luvatrix/audit.db
```

Audit to JSONL and summarize:

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --render headless --ticks 120 --audit-jsonl ./.luvatrix/audit.jsonl
uv run --python 3.14 python main.py audit-report --audit-jsonl ./.luvatrix/audit.jsonl
```

Energy safety monitor mode:

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --sensor-backend macos --energy-safety monitor --ticks 300
```

Energy safety enforce mode:

```bash
uv run --python 3.14 python main.py run-app examples/app_protocol/input_sensor_logger --sensor-backend macos --energy-safety enforce --energy-critical-streak 3 --ticks 300
```

## 2. Troubleshooting Decision Tree

```text
Run failed?
  -> Manifest parse error?
     -> Validate app.toml required fields and entrypoint format (module:symbol)
  -> Protocol/version error?
     -> Check protocol_version and min/max runtime bounds
  -> Variant resolution error?
     -> Check platform_support and variants os/arch/module_root
  -> Capability denial?
     -> Check required_capabilities and capability policy wiring
  -> No output/audit mismatch?
     -> Check window.write usage, audit sink args, and runtime completion summary
```

## 3. Common Incidents and Recovery

Incident: unsupported host platform

1. Symptom: runtime rejects with unsupported host OS message.
2. Recovery: update `platform_support` or move run to supported host.
3. Preventive: include platform matrix in app README and CI coverage.

Incident: no matching variant

1. Symptom: runtime reports no variant for host os/arch.
2. Recovery: add a matching `[[variants]]` entry or provide OS-only fallback.
3. Preventive: test both arch-specific and OS-only resolution paths.

Incident: `module_root` escapes app directory

1. Symptom: runtime rejects variant module root.
2. Recovery: replace path with app-relative module root.
3. Preventive: avoid `..` in variant module paths.

Incident: protocol bounds reject startup

1. Symptom: runtime rejects with min/max runtime protocol message.
2. Recovery: align bounds to supported runtime protocol.
3. Preventive: keep compatibility policy and app manifests synchronized.

Incident: required capability denied

1. Symptom: runtime fails fast before loop.
2. Recovery: grant required capability or remove it from manifest if not needed.
3. Preventive: classify capabilities as required vs optional correctly.

## 4. Audit and Log Verification Steps

For each operational run:

1. confirm CLI summary prints `run complete: ticks=... frames=...`
2. verify audit sink file exists and is non-empty (`.db` or `.jsonl`)
3. run `main.py audit-report` and check expected action counts
4. verify capability actions include expected grants/denials
5. verify security events include expected sensor/HDI gating when applicable

Quick verification commands:

```bash
uv run --python 3.14 python main.py audit-report --audit-sqlite ./.luvatrix/audit.db
uv run --python 3.14 python main.py audit-report --audit-jsonl ./.luvatrix/audit.jsonl
```

## 5. Operator Test Pack

Use this deterministic pack before milestone review:

```bash
uv run pytest tests/test_protocol_governance.py tests/test_app_runtime.py tests/test_unified_runtime.py
```

Optional focused checks:

```bash
uv run pytest tests/test_app_runtime.py -k "variant or protocol"
```
