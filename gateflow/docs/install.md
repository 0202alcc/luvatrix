# Installation Paths

## uvx

Run directly from source checkout:

```bash
uvx --from ./gateflow gateflow --help
```

Run a command against a workspace:

```bash
uvx --from ./gateflow gateflow --root /path/to/workspace validate all
```

## pipx (planned publishing path)

```bash
pipx install gateflow
gateflow --help
```

`pipx` works once pre-release artifacts are published.

## Build and smoke-check wheel/sdist

```bash
cd gateflow
uv run python -m build
uvx --from dist/*.whl gateflow --help
```
