from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import metadata, resources
import json
from pathlib import Path
import shutil


APP_TEMPLATES = ("basic", "full-suite", "camera")
NATIVE_TARGETS = ("android", "ios")
NATIVE_SCAFFOLD_METADATA = ".luvatrix-scaffold.json"
NATIVE_SCAFFOLD_UPDATES = ".luvatrix-scaffold-updates"


@dataclass(frozen=True)
class ScaffoldResult:
    path: Path
    created_files: tuple[Path, ...]


@dataclass(frozen=True)
class NativeScaffoldUpgradeResult:
    path: Path
    updated_files: tuple[Path, ...]
    added_files: tuple[Path, ...]
    removed_files: tuple[Path, ...]
    conflicted_files: tuple[Path, ...]
    candidate_dir: Path
    adopted: bool = False


def init_app(
    app_dir: str | Path,
    *,
    template: str = "basic",
    platform_support: list[str] | tuple[str, ...] | None = None,
    force: bool = False,
) -> ScaffoldResult:
    if template not in APP_TEMPLATES:
        raise ValueError(f"unsupported app template: {template}")
    root = Path(app_dir)
    _ensure_empty_or_force(root, force=force)
    root.mkdir(parents=True, exist_ok=True)

    support = list(platform_support or _default_platform_support(template))
    files = _app_template_files(template, support)
    created: list[Path] = []
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        created.append(target)
    return ScaffoldResult(path=root, created_files=tuple(created))


def init_native_project(
    app_dir: str | Path,
    *,
    target: str,
    out: str | Path | None = None,
    force: bool = False,
) -> ScaffoldResult:
    if target not in NATIVE_TARGETS:
        raise ValueError(f"unsupported native target: {target}")
    app_path = Path(app_dir)
    native_path = Path(out) if out is not None else default_native_project_dir(app_path, target)
    _ensure_empty_or_force(native_path, force=force)
    native_path.parent.mkdir(parents=True, exist_ok=True)

    template_root = resources.files("luvatrix_core").joinpath("templates", "native", target)
    with resources.as_file(template_root) as source:
        shutil.copytree(
            source,
            native_path,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
    _write_native_scaffold_metadata(
        native_path,
        target=target,
        files=_scaffold_file_hashes(native_path),
        pending_conflicts=(),
    )
    return ScaffoldResult(path=native_path, created_files=tuple(sorted(p for p in native_path.rglob("*") if p.is_file())))


def upgrade_native_project(
    app_dir: str | Path,
    *,
    target: str,
    out: str | Path | None = None,
    adopt: bool = False,
) -> NativeScaffoldUpgradeResult:
    """Safely reconcile an app-owned native project with the current template."""
    if target not in NATIVE_TARGETS:
        raise ValueError(f"unsupported native target: {target}")
    app_path = Path(app_dir)
    native_path = Path(out) if out is not None else default_native_project_dir(app_path, target)
    if not native_path.is_dir():
        raise FileNotFoundError(f"native project not found: {native_path}")
    _reject_scaffold_symlink(native_path, native_path)

    metadata_path = native_path / NATIVE_SCAFFOLD_METADATA
    version = _luvatrix_version()
    candidate_dir = native_path / NATIVE_SCAFFOLD_UPDATES / version
    _reject_scaffold_symlink(native_path, metadata_path)
    _reject_scaffold_symlink(native_path, candidate_dir)
    template_root = resources.files("luvatrix_core").joinpath("templates", "native", target)
    with resources.as_file(template_root) as source:
        latest = _scaffold_file_hashes(source)
        if not metadata_path.exists():
            if not adopt:
                raise RuntimeError(
                    f"{native_path} has no scaffold provenance; rerun with --adopt to preserve existing custom files"
                )
            if candidate_dir.exists():
                shutil.rmtree(candidate_dir)
            adopted_files: dict[str, str] = {}
            adoption_conflicts: list[Path] = []
            for relative, digest in sorted(latest.items()):
                relative_path = _safe_scaffold_relative_path(relative)
                current = native_path / relative_path
                _reject_scaffold_symlink(native_path, current)
                if current.is_file() and _sha256(current) == digest:
                    adopted_files[relative] = digest
                    continue
                candidate = candidate_dir / relative_path
                candidate.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / relative_path, candidate)
                adoption_conflicts.append(current)
            _write_native_scaffold_metadata(
                native_path,
                target=target,
                files=adopted_files,
                pending_conflicts=tuple(str(path.relative_to(native_path)) for path in adoption_conflicts),
            )
            return NativeScaffoldUpgradeResult(
                path=native_path,
                updated_files=(),
                added_files=(),
                removed_files=(),
                conflicted_files=tuple(adoption_conflicts),
                candidate_dir=candidate_dir,
                adopted=True,
            )

        scaffold_metadata = _read_native_scaffold_metadata(metadata_path, target=target)
        recorded = dict(scaffold_metadata["files"])
        if candidate_dir.exists():
            shutil.rmtree(candidate_dir)

        updated: list[Path] = []
        added: list[Path] = []
        removed: list[Path] = []
        conflicted: list[Path] = []
        next_hashes = dict(recorded)

        for relative, latest_hash in sorted(latest.items()):
            relative_path = _safe_scaffold_relative_path(relative)
            current = native_path / relative_path
            _reject_scaffold_symlink(native_path, current)
            template_file = source / relative_path
            if not current.exists():
                current.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(template_file, current)
                next_hashes[relative] = latest_hash
                added.append(current)
                continue
            current_hash = _sha256(current)
            if current_hash == latest_hash:
                next_hashes[relative] = latest_hash
                continue
            if recorded.get(relative) == current_hash:
                shutil.copy2(template_file, current)
                next_hashes[relative] = latest_hash
                updated.append(current)
                continue
            candidate = candidate_dir / relative_path
            candidate.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_file, candidate)
            conflicted.append(current)

        for relative, recorded_hash in sorted(recorded.items()):
            if relative in latest:
                continue
            relative_path = _safe_scaffold_relative_path(relative)
            current = native_path / relative_path
            _reject_scaffold_symlink(native_path, current)
            if not current.exists():
                next_hashes.pop(relative, None)
            elif _sha256(current) == recorded_hash:
                current.unlink()
                next_hashes.pop(relative, None)
                removed.append(current)
            else:
                conflicted.append(current)

    _write_native_scaffold_metadata(
        native_path,
        target=target,
        files=next_hashes,
        pending_conflicts=tuple(str(path.relative_to(native_path)) for path in conflicted),
    )
    return NativeScaffoldUpgradeResult(
        path=native_path,
        updated_files=tuple(updated),
        added_files=tuple(added),
        removed_files=tuple(removed),
        conflicted_files=tuple(conflicted),
        candidate_dir=candidate_dir,
    )


def default_native_project_dir(app_dir: str | Path, target: str) -> Path:
    if target not in NATIVE_TARGETS:
        raise ValueError(f"unsupported native target: {target}")
    return Path(app_dir) / ".luvatrix" / target


def resolve_native_project_dir(
    app_dir: str | Path,
    target: str,
    explicit: str | Path | None = None,
) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    candidate = default_native_project_dir(app_dir, target)
    if candidate.exists():
        return candidate
    return None


def _ensure_empty_or_force(path: Path, *, force: bool) -> None:
    if not path.exists():
        return
    if force:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return
    if path.is_dir() and not any(path.iterdir()):
        return
    raise FileExistsError(f"{path} already exists; pass --force to replace it")


def _scaffold_file_hashes(root: Path) -> dict[str, str]:
    ignored_roots = {NATIVE_SCAFFOLD_METADATA, NATIVE_SCAFFOLD_UPDATES}
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.relative_to(root).parts[0] not in ignored_roots
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_native_scaffold_metadata(
    native_path: Path,
    *,
    target: str,
    files: dict[str, str],
    pending_conflicts: tuple[str, ...],
) -> None:
    payload = {
        "schema_version": 1,
        "target": target,
        "luvatrix_version": _luvatrix_version(),
        "files": dict(sorted(files.items())),
        "pending_conflicts": list(sorted(pending_conflicts)),
    }
    (native_path / NATIVE_SCAFFOLD_METADATA).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_native_scaffold_metadata(path: Path, *, target: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid native scaffold metadata: {path}") from exc
    if payload.get("schema_version") != 1 or payload.get("target") != target:
        raise RuntimeError(f"native scaffold metadata does not match target {target!r}: {path}")
    files = payload.get("files")
    if not isinstance(files, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in files.items()):
        raise RuntimeError(f"native scaffold metadata has invalid file hashes: {path}")
    for relative in files:
        _safe_scaffold_relative_path(relative)
    return payload


def _safe_scaffold_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuntimeError(f"unsafe native scaffold metadata path: {value!r}")
    return path


def _reject_scaffold_symlink(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"native scaffold path escapes project: {path}") from exc
    current = root
    if current.is_symlink():
        raise RuntimeError(f"native scaffold path contains symlink: {current}")
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"native scaffold path contains symlink: {current}")


def _luvatrix_version() -> str:
    try:
        return metadata.version("luvatrix")
    except metadata.PackageNotFoundError:
        return "source"


def _default_platform_support(template: str) -> tuple[str, ...]:
    if template == "camera":
        return ("android",)
    return ("macos", "ios", "android", "web")


def _app_template_files(template: str, platform_support: list[str]) -> dict[str, str]:
    support_literal = ", ".join(f'"{value}"' for value in platform_support)
    if template == "camera":
        app_id = "my_luvatrix_camera"
        optional = '"hdi.touch", "hdi.keyboard", "sensor.camera", "sensor.display"'
        body = _camera_app_main()
    elif template == "full-suite":
        app_id = "my_luvatrix_full_suite"
        optional = '"hdi.keyboard", "hdi.mouse", "hdi.trackpad", "hdi.touch", "sensor.motion"'
        body = _full_suite_app_main()
    else:
        app_id = "my_luvatrix_app"
        optional = '"hdi.keyboard", "hdi.mouse", "hdi.touch"'
        body = _basic_app_main()

    app_toml = f'''app_id = "{app_id}"
protocol_version = "3"
entrypoint = "app_main:create"
platform_support = [{support_literal}]
required_capabilities = ["window.write"]
optional_capabilities = [{optional}]

[display]
native_width = 393
native_height = 852
bar_color_rgba = [0, 0, 0, 255]
default_coordinate_frame = "screen_tl"
title = "My Luvatrix App"

[render]
preferred = "auto"
fallbacks = ["scene", "ui", "matrix"]

[web]
pyodide_packages = []
assets = []
api_base_url = "/api"
'''
    if platform_support == ["android"]:
        readme = """# My Luvatrix App

Validate and smoke-test locally:

```bash
luvatrix validate-app . --render android-emulator
luvatrix run-app . --render headless --ticks 1
```

Create and run an Android native project:

```bash
luvatrix init-native . --target android --out android
luvatrix run-app . --render android-emulator --native-project android
```
"""
    else:
        readme = """# My Luvatrix App

Run locally:

```bash
luvatrix validate-app . --render headless
luvatrix run-app . --render headless --ticks 1
luvatrix build-web . --out dist/web
```

Add native scaffold projects when needed:

```bash
luvatrix init-native . --target android --out android
luvatrix init-native . --target ios --out ios
```
"""
    return {
        "app.toml": app_toml,
        "app_main.py": body,
        "README.md": readme,
    }


def _basic_app_main() -> str:
    return '''from luvatrix.app import App


class MyApp(App):
    def render(self):
        with self.frame(clear=(14, 18, 26, 255)) as frame:
            frame.rect(x=24, y=24, width=345, height=120, color=(32, 120, 180, 255))
            frame.rect(x=44, y=62, width=305, height=44, color=(255, 255, 255, 255))


def create():
    return MyApp()
'''


def _full_suite_app_main() -> str:
    return '''from luvatrix.app import App


class MyApp(App):
    def init(self, ctx):
        super().init(ctx)
        self.ticks = 0

    def render(self):
        self.ticks += 1
        pulse = (self.ticks * 7) % 180
        with self.frame(clear=(10, 12, 18, 255)) as frame:
            frame.rect(x=24, y=24, width=345, height=804, color=(22, 28, 38, 255))
            frame.rect(x=44, y=56, width=305, height=80, color=(40 + pulse, 96, 150, 255))
            frame.rect(x=44, y=164, width=140, height=140, color=(240, 210, 90, 255))
            frame.rect(x=209, y=164, width=140, height=140, color=(90, 190, 150, 255))
            frame.rect(x=44, y=332, width=305, height=44, color=(245, 245, 245, 255))


def create():
    return MyApp()
'''


def _camera_app_main() -> str:
    return '''from luvatrix.app import App


class CameraApp(App):
    def render(self):
        with self.frame(clear=(8, 8, 10, 255)) as frame:
            frame.rect(x=32, y=64, width=329, height=500, color=(18, 24, 32, 255))
            frame.rect(x=64, y=604, width=265, height=64, color=(230, 230, 230, 255))


def create():
    return CameraApp()
'''
