"""Config and token persistence.

Everything lives under one config dir (default ``~/.config/spotify-light``,
override with ``SPOTIFY_LIGHT_CONFIG_DIR``). Tokens are written owner-only
(0600); they never touch the app folder or the repo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import sl_oauth

_CONFIG_ENV = "SPOTIFY_LIGHT_CONFIG_DIR"
_CLIENT_ID_FILE = "client_id.txt"
_TOKENS_FILE = "tokens.json"


def config_dir() -> Path:
    override = os.environ.get(_CONFIG_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "spotify-light"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def load_client_id(path: Path) -> str | None:
    # Environment wins so CI/dev shells can inject a client id without files.
    env_value = os.environ.get("SPOTIFY_LIGHT_CLIENT_ID", "").strip()
    if env_value:
        return env_value
    try:
        value = (path / _CLIENT_ID_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def save_client_id(path: Path, client_id: str) -> None:
    _ensure_dir(path)
    target = path / _CLIENT_ID_FILE
    target.write_text(client_id.strip() + "\n", encoding="utf-8")
    os.chmod(target, 0o600)


def load_tokens(path: Path) -> sl_oauth.TokenSet | None:
    try:
        payload = json.loads((path / _TOKENS_FILE).read_text(encoding="utf-8"))
        return sl_oauth.TokenSet.from_json(payload)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_tokens(path: Path, tokens: sl_oauth.TokenSet) -> None:
    _ensure_dir(path)
    target = path / _TOKENS_FILE
    target.write_text(json.dumps(tokens.to_json(), indent=2), encoding="utf-8")
    os.chmod(target, 0o600)


def clear_tokens(path: Path) -> None:
    try:
        (path / _TOKENS_FILE).unlink()
    except FileNotFoundError:
        pass
