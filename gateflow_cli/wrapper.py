from __future__ import annotations

import os
import shlex
import subprocess
import sys

DEFAULT_GATEFLOW_CMD = "uvx --from gateflow==1.0.0 gateflow"
COMMAND_ENV_VAR = "LUVATRIX_GATEFLOW_WRAPPER_CMD"


def _resolve_base_command() -> list[str]:
    raw = os.environ.get(COMMAND_ENV_VAR, DEFAULT_GATEFLOW_CMD).strip()
    if not raw:
        raw = DEFAULT_GATEFLOW_CMD
    return shlex.split(raw)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    base = _resolve_base_command()
    cmd = base + args
    env = os.environ.copy()
    # Keep uvx artifacts local to the repo when using the default standalone path.
    if base == shlex.split(DEFAULT_GATEFLOW_CMD):
        env.setdefault("UV_CACHE_DIR", "./.uv-cache")
        env.setdefault("UV_TOOL_DIR", "./gateflow/.uv-tools")
    try:
        proc = subprocess.run(cmd, check=False, env=env)
    except FileNotFoundError as exc:
        missing = cmd[0] if cmd else "<empty>"
        print(
            f"gateflow wrapper error: failed to execute '{missing}': {exc}. "
            f"Set {COMMAND_ENV_VAR} to an installed standalone gateflow command.",
            file=sys.stderr,
        )
        return 127
    return proc.returncode


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
