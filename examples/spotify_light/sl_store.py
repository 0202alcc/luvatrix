"""Config and token persistence. Stub module — see tests."""
from __future__ import annotations

from pathlib import Path


def config_dir() -> Path: raise NotImplementedError
def load_client_id(path: Path) -> str | None: raise NotImplementedError
def save_client_id(path: Path, client_id: str) -> None: raise NotImplementedError
def load_tokens(path: Path): raise NotImplementedError
def save_tokens(path: Path, tokens) -> None: raise NotImplementedError
def clear_tokens(path: Path) -> None: raise NotImplementedError
