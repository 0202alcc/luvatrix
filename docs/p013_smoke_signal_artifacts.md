# P-013 Smoke Signal and Artifact Linking

## Objective

`T-403` adds a CI-visible smoke summary with deterministic artifact links for P-013 gate commands.

## Components

1. Summary renderer: `ops/ci/render_ci_smoke_summary.py`
2. CI workflow: `.github/workflows/p013-ci-smoke-signals.yml`
3. Smoke artifact index: `artifacts/p013/smoke_index.json`
4. Summary markdown: `artifacts/p013/smoke_summary.md`

## Verification Command

```bash
PYTHONPATH=. uv run --with pytest pytest tests/test_render_ci_smoke_summary.py -q
```

## Expected Output

The workflow writes a markdown table with check name, pass/fail status, and artifact filename/link for each smoke gate.
