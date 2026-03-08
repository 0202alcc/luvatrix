# gateflow

Standalone GateFlow CLI package extracted from Luvatrix.

## Install and Run

### `uvx` (current pre-release workflow)

```bash
uvx --from ./gateflow gateflow --help
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
- `milestones`
- `tasks`
- `boards`
- `frameworks`
- `backlog`
