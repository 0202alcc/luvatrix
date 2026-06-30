from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
import shutil


APP_TEMPLATES = ("basic", "full-suite", "camera")
NATIVE_TARGETS = ("android", "ios")


@dataclass(frozen=True)
class ScaffoldResult:
    path: Path
    created_files: tuple[Path, ...]


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
    return ScaffoldResult(path=native_path, created_files=tuple(sorted(p for p in native_path.rglob("*") if p.is_file())))


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
    readme = f"""# My Luvatrix App

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
