from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil

from luvatrix_core.core.app_runtime import AppManifest, AppRuntime
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_core.core.hdi_thread import HDIThread
from luvatrix_core.core.sensor_manager import SensorManagerThread


WEB_BUILD_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WebBuildResult:
    app_dir: Path
    out_dir: Path
    manifest: AppManifest
    index_path: Path
    manifest_json_path: Path


def build_web_app(app_dir: str | Path, out_dir: str | Path) -> WebBuildResult:
    app_path = Path(app_dir).resolve()
    out_path = Path(out_dir).resolve()
    manifest = _load_web_manifest(app_path)
    if manifest.platform_support and "web" not in manifest.platform_support:
        raise RuntimeError(
            f"app `{manifest.app_id}` does not support web; supported={','.join(sorted(manifest.platform_support))}"
        )

    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    _copy_runtime_assets(out_path)
    _copy_python_shim(out_path)
    _copy_first_party_python_packages(out_path / "py")
    _copy_app_files(app_path, out_path / "app", exclude_paths={out_path})
    _copy_declared_assets(app_path, out_path / "assets", manifest.web.assets)
    _write_file_manifest(out_path / "py", out_path / "py_manifest.json", url_prefix="./py")
    _write_file_manifest(out_path / "app", out_path / "app_files.json", url_prefix="./app")

    manifest_json_path = out_path / "app_manifest.json"
    manifest_json_path.write_text(json.dumps(_web_manifest_payload(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return WebBuildResult(
        app_dir=app_path,
        out_dir=out_path,
        manifest=manifest,
        index_path=out_path / "index.html",
        manifest_json_path=manifest_json_path,
    )


def _load_web_manifest(app_path: Path) -> AppManifest:
    runtime = AppRuntime(
        matrix=WindowMatrix(height=1, width=1),
        hdi=HDIThread(source=None),
        sensor_manager=SensorManagerThread(providers={}),
        host_os="web",
    )
    return runtime.load_manifest(app_path)


def _copy_runtime_assets(out_path: Path) -> None:
    src = Path(__file__).with_name("runtime_assets")
    for child in src.iterdir():
        dest = out_path / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)


def _copy_python_shim(out_path: Path) -> None:
    src = Path(__file__).with_name("python_shim")
    shutil.copytree(src, out_path / "py")


def _copy_first_party_python_packages(dest: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    for package_name in ("luvatrix_ui",):
        source = project_root / package_name
        if not source.exists():
            continue
        _copy_python_package(source, dest / package_name)


def _copy_python_package(source: Path, dest: Path) -> None:
    for child in source.rglob("*"):
        if child.is_dir():
            continue
        if "__pycache__" in child.parts or child.suffix in {".pyc", ".pyo"}:
            continue
        relative = child.relative_to(source)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)


def _copy_app_files(app_path: Path, dest: Path, *, exclude_paths: set[Path] | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    resolved_excludes = {path.resolve() for path in exclude_paths or set()}
    for child in app_path.rglob("*"):
        resolved_child = child.resolve()
        if any(resolved_child == excluded or excluded in resolved_child.parents for excluded in resolved_excludes):
            continue
        if child.is_dir():
            continue
        if "__pycache__" in child.parts or child.suffix in {".pyc", ".pyo"}:
            continue
        relative = child.relative_to(app_path)
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)


def _copy_declared_assets(app_path: Path, dest: Path, assets: list[str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        source = (app_path / asset).resolve()
        app_root = app_path.resolve()
        if source != app_root and app_root not in source.parents:
            raise ValueError(f"web asset escapes app directory: {asset}")
        if not source.exists():
            raise FileNotFoundError(f"web asset not found: {asset}")
        target = dest / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def _write_file_manifest(root: Path, manifest_path: Path, *, url_prefix: str) -> None:
    entries: list[dict[str, str]] = []
    for child in sorted(root.rglob("*")):
        if child.is_dir():
            continue
        rel = child.relative_to(root).as_posix()
        entries.append({"path": rel, "url": f"{url_prefix}/{rel}"})
    manifest_path.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _web_manifest_payload(manifest: AppManifest) -> dict[str, object]:
    return {
        "schema_version": WEB_BUILD_SCHEMA_VERSION,
        "app_id": manifest.app_id,
        "protocol_version": manifest.protocol_version,
        "entrypoint": manifest.entrypoint,
        "platform_support": manifest.platform_support,
        "display": {
            "native_width": manifest.display_native_width,
            "native_height": manifest.display_native_height,
            "title": manifest.display_title,
            "icon": manifest.display_icon,
            "bar_color_rgba": list(manifest.display_bar_color_rgba),
            "default_coordinate_frame": manifest.display_default_coordinate_frame,
        },
        "render": {
            "preferred": manifest.render_preferred,
            "fallbacks": manifest.render_fallbacks,
        },
        "web": asdict(manifest.web),
    }
