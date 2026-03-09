from __future__ import annotations

from pathlib import Path

from examples.app_protocol.training_protocol import build_app, cli_main


APP_DIR = Path(__file__).resolve().parent


def create():
    return build_app(APP_DIR)


def main() -> int:
    return cli_main(APP_DIR)


if __name__ == "__main__":
    raise SystemExit(main())
