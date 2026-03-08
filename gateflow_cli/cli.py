from __future__ import annotations

import sys

from gateflow_cli.wrapper import main as wrapper_main

DEPRECATION_MESSAGE = (
    "gateflow_cli.cli is deprecated and no longer provides an in-repo CLI implementation.\n"
    "Use standalone gateflow instead:\n"
    "  uv run gateflow --root <repo> <command>\n"
    "  uvx --from gateflow==0.1.0a3 gateflow --root <repo> <command>\n"
)


def main(argv: list[str] | None = None) -> int:
    print(DEPRECATION_MESSAGE, file=sys.stderr)
    return wrapper_main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
