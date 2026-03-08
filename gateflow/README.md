# gateflow

Standalone GateFlow CLI package extracted from Luvatrix.

Current pre-release version: `0.1.0a2`.

## Install and Run

### `uvx` (current pre-release workflow)

```bash
UV_CACHE_DIR=./.uv-cache UV_TOOL_DIR=./gateflow/.uv-tools uvx --from ./gateflow gateflow --help
```

### Local editable install

```bash
cd gateflow
uv sync
uv run gateflow --help
```

### Future `pipx` path

After publishing pre-release distributions to an index, install with:

```bash
pipx install gateflow
gateflow --help
```

## Command Surface

The standalone CLI exposes the extracted command groups:

- `init`
- `config`
- `validate`
- `api`
- `render`
- `import-luvatrix`
- `milestones`
- `tasks`
- `boards`
- `frameworks`
- `backlog`

`import-luvatrix` supports `--check` to emit deterministic drift output and non-zero exit when `.gateflow/*` diverges from `ops/planning/*`.
