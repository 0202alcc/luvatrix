from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import shutil


PLATFORM_RUNTIME_DIRS = frozenset({"android", "ios", "macos", "web"})
BASE_IGNORE_PATTERNS = ("__pycache__", "*.pyc", ".pytest_cache")


def make_target_package_ignore(
    target_platform: str,
    extra_patterns: Iterable[str] = (),
) -> Callable[[str, list[str]], set[str]]:
    target = target_platform.lower()
    if target not in PLATFORM_RUNTIME_DIRS:
        raise ValueError(f"unsupported platform runtime target: {target_platform!r}")

    pattern_ignore = shutil.ignore_patterns(*BASE_IGNORE_PATTERNS, *tuple(extra_patterns))

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(pattern_ignore(directory, names))
        path = Path(directory)
        available = set(names)

        if path.name == "platform" and path.parent.name == "luvatrix_core":
            ignored.update(available & (PLATFORM_RUNTIME_DIRS - {target}))

        if path.name == "native" and path.parent.name == "templates":
            ignored.update(available & (PLATFORM_RUNTIME_DIRS - {target}))

        return ignored

    return _ignore


def copy_package_tree_for_target(src: Path, dst: Path, *, target_platform: str) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=make_target_package_ignore(target_platform))
