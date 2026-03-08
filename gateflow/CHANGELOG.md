# Changelog

## 0.1.0a2 - 2026-03-08

- Hard-deprecated legacy in-repo `gateflow_cli.cli` path and routed wrapper usage to standalone command execution.
- Added continuity CI gate in Luvatrix validating `uv run gateflow --root . validate all`.
- Removed stale legacy `gateflow_cli` implementation modules from Luvatrix root package.
- Added wrapper environment defaults for local uvx tool/cache directories (`UV_CACHE_DIR`, `UV_TOOL_DIR`) to improve reliability.
- Added release migration guidance for `LUVATRIX_GATEFLOW_WRAPPER_CMD` and standalone command paths.

## 0.1.0a1 - 2026-03-07

- Initial standalone CLI extraction from Luvatrix.
