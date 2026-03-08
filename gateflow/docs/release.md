# Pre-Release Notes: `v0.1.0a1`

## Scope

- Extracted standalone `gateflow` package skeleton and full CLI module surface.
- Added install paths for `uvx` and future `pipx` usage.
- Ported CLI tests and snapshot fixtures into package-local test suite.

## Publish Checklist

1. Build artifacts:

```bash
cd gateflow
uv run --with build python -m build
```

2. Smoke run from built wheel:

```bash
UV_CACHE_DIR=../.uv-cache UV_TOOL_DIR=./.uv-tools uvx --from dist/gateflow-0.1.0a1-py3-none-any.whl gateflow --help
```

3. Push Git tag:

```bash
git tag -a gateflow-v0.1.0a1 -m "gateflow pre-release v0.1.0a1"
git push origin gateflow-v0.1.0a1
```

4. Publish install docs from:
- `gateflow/README.md`
- `gateflow/docs/install.md`

## Validation Evidence

- `cd gateflow && uv run --with pytest pytest tests -q`
- `UV_CACHE_DIR=./.uv-cache UV_TOOL_DIR=./gateflow/.uv-tools uvx --from ./gateflow gateflow --help`
