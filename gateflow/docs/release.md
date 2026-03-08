# Pre-Release Notes: `v0.1.0a2`

## Scope

- Extracted standalone `gateflow` package skeleton and full CLI module surface.
- Added install paths for `uvx` and future `pipx` usage.
- Ported CLI tests and snapshot fixtures into package-local test suite.
- Added post-P047 hardening: wrapper deprecation path, continuity CI gate, and cleanup of legacy in-repo CLI internals.

## Publish Checklist

1. Build artifacts:

```bash
cd gateflow
uv run --with build python -m build
```

2. Smoke run from built wheel:

```bash
UV_CACHE_DIR=../.uv-cache UV_TOOL_DIR=./.uv-tools uvx --from dist/gateflow-0.1.0a2-py3-none-any.whl gateflow --help
```

3. Push Git tag:

```bash
git tag -a gateflow-v0.1.0a2 -m "gateflow pre-release v0.1.0a2"
git push origin gateflow-v0.1.0a2
```

4. Publish install docs from:
- `gateflow/README.md`
- `gateflow/docs/install.md`

## Validation Evidence

- `cd gateflow && uv run --with pytest pytest tests -q`
- `UV_CACHE_DIR=./.uv-cache UV_TOOL_DIR=./gateflow/.uv-tools uvx --from ./gateflow gateflow --help`

## Post-P047 Migration Guidance

1. Preferred command paths in Luvatrix:

```bash
uv run gateflow --root /path/to/repo validate all
uvx --from ./gateflow gateflow --root /path/to/repo validate all
```

2. Wrapper override (use installed binary or custom command):

```bash
export LUVATRIX_GATEFLOW_WRAPPER_CMD="gateflow"
uv run gateflow --root /path/to/repo api GET /milestones
```

3. Legacy `gateflow_cli.cli` is hard-deprecated and now forwards to standalone gateflow with migration warning.

## Optional Publishing Path (`pipx`)

When publish credentials are available:

1. Build artifacts:

```bash
cd gateflow
uv run --with build python -m build
```

2. Validate package metadata:

```bash
uv run --with twine twine check dist/*
```

3. Upload to package index:

```bash
uv run --with twine twine upload dist/*
```

4. Verify `pipx` install:

```bash
pipx install gateflow
gateflow --help
```

## 0.1.0a3 Proposed Scope

1. Error UX improvements:
- normalize actionable remediation text across `api`, `validate`, and resource commands.

2. Stricter schema diagnostics:
- enrich validation failures with field-level mismatch hints and deterministic ordering.

3. Import drift explainability:
- attach concise mismatch-class summaries and top remediation actions in drift output.

4. Deprecation execution support:
- use `ops/planning/api/planning_api_deprecation_dashboard.py --root <repo>` to track legacy endpoint usage through sunset (`2026-06-30`).
