# App Protocol Conformance Matrix

Current runtime protocol is `3` (`CURRENT_PROTOCOL_VERSION` in `luvatrix_core/core/protocol_governance.py`).

## Runtime Version Matrix

| Runtime version | Accepts v1 | Accepts v2 | Accepts v3 | v1 warning | v2 warning | v2 process lane |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | yes | yes | yes | yes (deprecated) | yes (deprecated) | yes (`stdio_jsonl`) |

## Required Tests

1. `tests/test_protocol_governance.py`
- verifies support and bounds behavior for v1, v2, and v3.

2. `tests/test_app_runtime.py`
- verifies manifest parsing and runtime table validation.

3. `tests/test_unified_runtime.py`
- verifies in-process lane and v2 Python process lane execution.

4. `tests/test_planes_protocol.py`
- verifies Planes validation + compile contract (used by planning UI profile).

## CI Command

```bash
PYTHONPATH=. uv run --extra desktop --with pytest pytest \
  tests/test_protocol_governance.py \
  tests/test_app_runtime.py \
  tests/test_unified_runtime.py \
  tests/test_planes_protocol.py
```
