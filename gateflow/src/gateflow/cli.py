from __future__ import annotations

import argparse

from gateflow import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gateflow")
    parser.add_argument("--version", action="store_true", help="Print package version.")
    parser.add_argument("--root", default=".", help="Workspace root path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
