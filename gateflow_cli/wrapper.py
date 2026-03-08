from __future__ import annotations

import os
import shlex
import subprocess
import sys

DEFAULT_GATEFLOW_CMD = "uvx --from ./gateflow gateflow"
COMMAND_ENV_VAR = "LUVATRIX_GATEFLOW_WRAPPER_CMD"


def _resolve_base_command() -> list[str]:
    raw = os.environ.get(COMMAND_ENV_VAR, DEFAULT_GATEFLOW_CMD).strip()
    if not raw:
        raw = DEFAULT_GATEFLOW_CMD
    return shlex.split(raw)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cmd = _resolve_base_command() + args
    try:
        proc = subprocess.run(cmd, check=False)
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
