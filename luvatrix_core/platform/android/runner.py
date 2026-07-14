from __future__ import annotations

import ast
from collections.abc import Iterable
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import tomllib
import urllib.error
import urllib.request

from luvatrix_core import __version__
from luvatrix_core.platform.package_sync import copy_package_tree_for_target
from luvatrix_core.scaffold import resolve_native_project_dir


DEFAULT_ANDROID_PACKAGE = "com.luvatrix.app"
ANDROID_GENERATED_GITIGNORE_RULES = (
    "app/luvatrix-android-accel.txt",
    "app/wheels/",
    "app/.cxx/",
    "app/build/",
    "app/src/main/assets/luvatrix_launch_config.json",
    "app/src/main/python/luvatrix_launch_config.json",
)


def android_project_dir(repo_root: Path | None = None) -> Path:
    root = repo_root or Path.cwd()
    return root / "android"


def build_android_debug_apk(project_dir: Path | None = None) -> Path:
    project = (project_dir or android_project_dir()).resolve()
    gradlew = project / "gradlew"
    if not gradlew.exists():
        raise RuntimeError(f"Android Gradle wrapper not found at {gradlew}")
    subprocess.run([str(gradlew), "assembleDebug"], cwd=project, check=True, env=_android_subprocess_env())
    apk = project / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.exists():
        raise RuntimeError(f"debug APK not found at {apk}")
    return apk


def launch_android_app(
    *,
    package_name: str = DEFAULT_ANDROID_PACKAGE,
    device_id: str | None = None,
    import_probe: bool = False,
) -> None:
    adb = shutil.which("adb")
    if adb is None:
        raise RuntimeError("adb not found on PATH")
    prefix = _adb_prefix(adb, device_id=device_id)
    args = prefix + [
        "shell",
        "am",
        "start",
        "-n",
        f"{package_name}/.MainActivity",
    ]
    if import_probe:
        args.extend(["--ez", "luvatrix_import_probe", "true"])
    subprocess.run(args, check=True, env=_android_subprocess_env())


def write_android_launch_config(
    app_dir: Path,
    *,
    project_dir: Path | None = None,
    device_id: str | None = None,
    infer_device_dimensions: bool = False,
    render_scale: float = 1.0,
    render_mode: str = "auto",
    target_fps: int | None = None,
    present_fps: int | None = None,
    low_latency_mode: bool = True,
) -> Path:
    project = (project_dir or android_project_dir()).resolve()
    _ensure_android_generated_gitignore(project)
    dest = project / "app" / "src" / "main" / "assets" / "luvatrix_launch_config.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = _read_app_manifest(app_dir)
    display = _read_app_display_config(manifest)
    resolved_render_mode = _resolve_manifest_render_mode(render_mode, manifest)
    data = {
        "app_dir": "luvatrix_app",
        "source_app_dir": str(app_dir),
        "render_scale": float(render_scale),
        "render_mode": resolved_render_mode,
        "target_fps": target_fps,
        "present_fps": present_fps,
        "low_latency_mode": bool(low_latency_mode),
    }
    data.update(display)
    if infer_device_dimensions and ("native_width" not in data or "native_height" not in data):
        device_display = _android_device_logical_display_config(device_id=device_id)
        data.update({key: value for key, value in device_display.items() if key.startswith("device_")})
        if "native_width" not in data and "native_width" in device_display:
            data["native_width"] = device_display["native_width"]
        if "native_height" not in data and "native_height" in device_display:
            data["native_height"] = device_display["native_height"]
    dest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def _ensure_android_generated_gitignore(project_dir: Path) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    gitignore = project_dir / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    missing = [rule for rule in ANDROID_GENERATED_GITIGNORE_RULES if rule not in existing.splitlines()]
    if not missing:
        return gitignore

    if existing and not existing.endswith("\n"):
        existing += "\n"
    block = "# Luvatrix Android generated files\n" + "\n".join(missing) + "\n"
    gitignore.write_text(existing + block, encoding="utf-8")
    return gitignore


def _read_app_manifest(app_dir: Path) -> dict[str, object]:
    try:
        raw = tomllib.loads((app_dir / "app.toml").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_app_display_config(raw: dict[str, object]) -> dict[str, int]:
    display = raw.get("display")
    if not isinstance(display, dict):
        return {}
    out: dict[str, int] = {}
    for source_key, dest_key in (("native_width", "native_width"), ("native_height", "native_height")):
        try:
            value = int(display.get(source_key, 0))
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            out[dest_key] = value
    return out


def _resolve_manifest_render_mode(requested: str, raw: dict[str, object]) -> str:
    if requested != "auto":
        return requested
    render = raw.get("render")
    if not isinstance(render, dict):
        return requested
    preferred = str(render.get("preferred") or "").strip()
    return preferred if preferred in ("matrix", "scene") else requested


def _android_device_logical_display_config(*, device_id: str | None = None) -> dict[str, int]:
    adb = shutil.which("adb")
    if adb is None:
        return {}
    try:
        prefix = _adb_prefix(adb, device_id=device_id)
        size = _parse_wm_size(_adb_shell_text(prefix, "wm", "size"))
        density = _parse_wm_density(_adb_shell_text(prefix, "wm", "density"))
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        return {}
    if size is None or density is None or density <= 0:
        return {}
    physical_width, physical_height = size
    logical_width = max(1, int(round(float(physical_width) * 160.0 / float(density))))
    logical_height = max(1, int(round(float(physical_height) * 160.0 / float(density))))
    return {
        "native_width": logical_width,
        "native_height": logical_height,
        "device_physical_width": physical_width,
        "device_physical_height": physical_height,
        "device_density_dpi": density,
    }


def _adb_shell_text(prefix: list[str], *args: str) -> str:
    completed = subprocess.run(
        prefix + ["shell", *args],
        check=True,
        capture_output=True,
        text=True,
        env=_android_subprocess_env(),
    )
    return completed.stdout


def _parse_wm_size(output: str) -> tuple[int, int] | None:
    matches = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
    if not matches:
        matches = re.findall(r"\b(\d+)x(\d+)\b", output)
    if not matches:
        return None
    width, height = matches[-1]
    return int(width), int(height)


def _parse_wm_density(output: str) -> int | None:
    matches = re.findall(r"(?:Physical|Override) density:\s*(\d+)", output)
    if not matches:
        matches = re.findall(r"\b(\d{2,4})\b", output)
    if not matches:
        return None
    return int(matches[-1])


def run_android_emulator(
    app_dir: Path,
    *,
    device_id: str | None = None,
    package_name: str = DEFAULT_ANDROID_PACKAGE,
    native_project_dir: Path | None = None,
    import_probe: bool = False,
    render_scale: float = 1.0,
    render_mode: str = "auto",
    target_fps: int | None = None,
    present_fps: int | None = None,
    low_latency_mode: bool = True,
) -> None:
    device_id = device_id or _ensure_emulator_running()
    _run_android(
        app_dir,
        device_id=device_id,
        package_name=package_name,
        native_project_dir=native_project_dir,
        import_probe=import_probe,
        render_scale=render_scale,
        render_mode=render_mode,
        target_fps=target_fps,
        present_fps=present_fps,
        low_latency_mode=low_latency_mode,
    )


def run_android_device(
    app_dir: Path,
    *,
    device_id: str | None = None,
    package_name: str = DEFAULT_ANDROID_PACKAGE,
    native_project_dir: Path | None = None,
    import_probe: bool = False,
    render_scale: float = 1.0,
    render_mode: str = "auto",
    target_fps: int | None = None,
    present_fps: int | None = None,
    low_latency_mode: bool = True,
) -> None:
    _run_android(
        app_dir,
        device_id=device_id,
        package_name=package_name,
        native_project_dir=native_project_dir,
        import_probe=import_probe,
        render_scale=render_scale,
        render_mode=render_mode,
        target_fps=target_fps,
        present_fps=present_fps,
        low_latency_mode=low_latency_mode,
    )


def _run_android(
    app_dir: Path,
    *,
    device_id: str | None,
    package_name: str,
    native_project_dir: Path | None,
    import_probe: bool,
    render_scale: float,
    render_mode: str,
    target_fps: int | None,
    present_fps: int | None,
    low_latency_mode: bool,
) -> None:
    project = _resolve_android_project(app_dir, native_project_dir)
    write_android_launch_config(
        app_dir,
        project_dir=project,
        device_id=device_id,
        infer_device_dimensions=True,
        render_scale=render_scale,
        render_mode=render_mode,
        target_fps=target_fps,
        present_fps=present_fps,
        low_latency_mode=low_latency_mode,
    )
    sync_android_python_assets(app_dir, project_dir=project)
    apk = build_android_debug_apk(project)
    adb = shutil.which("adb")
    if adb is None:
        raise RuntimeError("adb not found on PATH")
    prefix = _adb_prefix(adb, device_id=device_id)
    force_stop_android_app(package_name=package_name, device_id=device_id)
    subprocess.run(prefix + ["install", "-r", str(apk)], check=True, env=_android_subprocess_env())
    force_stop_android_app(package_name=package_name, device_id=device_id)
    launch_android_app(package_name=package_name, device_id=device_id, import_probe=import_probe)


def _resolve_android_project(app_dir: Path, explicit: Path | None = None) -> Path:
    project = resolve_native_project_dir(app_dir, "android", explicit)
    if project is not None:
        return project.resolve()
    raise RuntimeError(
        "Android native project not found. Run "
        "`luvatrix init-native APP_DIR --target android --out APP_DIR/android` "
        "and then pass `--native-project APP_DIR/android`, or create the default "
        "`APP_DIR/.luvatrix/android` scaffold."
    )


def sync_android_python_assets(app_dir: Path, *, project_dir: Path) -> None:
    project = project_dir.resolve()
    py_dst = project / "app" / "src" / "main" / "python"
    py_dst.mkdir(parents=True, exist_ok=True)
    app_ignore = _make_android_app_ignore(project)

    all_pkg_names = ("luvatrix", "luvatrix_core", "luvatrix_ui", "luvatrix_plot")
    pkg_names = _android_python_packages_for_app(app_dir, exclude_dirs=(project,))
    for stale_pkg in set(all_pkg_names) - set(pkg_names):
        stale_dst = py_dst / stale_pkg
        if stale_dst.exists():
            shutil.rmtree(stale_dst)

    for pkg_name in pkg_names:
        src = _python_package_dir(pkg_name)
        dst = py_dst / pkg_name
        copy_package_tree_for_target(src, dst, target_platform="android")

    for rel in ("examples", "luvatrix_app"):
        dst = py_dst / rel
        if dst.exists():
            shutil.rmtree(dst)
    shutil.copytree(app_dir, py_dst / "luvatrix_app", ignore=app_ignore)
    (py_dst / "luvatrix_app" / "__init__.py").touch()
    _write_android_app_bundle(app_dir, py_dst=py_dst)

    config = project / "app" / "src" / "main" / "assets" / "luvatrix_launch_config.json"
    if config.exists():
        shutil.copy2(config, py_dst / "luvatrix_launch_config.json")
    accelerator_mode = os.getenv("LUVATRIX_ANDROID_ACCEL_DOWNLOAD", "auto").strip().lower()
    should_sync_accelerator = accelerator_mode == "on" or (
        accelerator_mode == "auto" and not _running_from_source_checkout()
    )
    if (project / "app" / "build.gradle.kts").is_file() and should_sync_accelerator:
        synced = sync_android_accelerator_wheels(project, version=__version__)
        if synced:
            print(f"[android] synced {len(synced)} native accelerator wheels")
    print(f"[android] synced Python assets for {app_dir}")


def sync_android_accelerator_wheels(project_dir: Path, *, version: str) -> tuple[Path, ...]:
    """Download verified CPython 3.14 Android wheels when this release provides them."""
    project = project_dir.resolve()
    app_dir = project / "app"
    requirement = app_dir / "luvatrix-android-accel.txt"
    cached = _cached_android_accelerator_wheels(app_dir, version=version)
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/luvatrix/{version}/json",
            timeout=20,
        ) as response:
            release = json.loads(response.read())
    except (OSError, ValueError, urllib.error.URLError):
        return cached

    normalized_version = str(version).replace("-", "_")
    pattern = re.compile(
        rf"^luvatrix-{re.escape(normalized_version)}-cp314-cp314-android_\d+_"
        r"(arm64_v8a|x86_64)\.whl$"
    )
    selected: dict[str, dict[str, object]] = {}
    for entry in release.get("urls", ()) if isinstance(release, dict) else ():
        if not isinstance(entry, dict):
            continue
        match = pattern.match(str(entry.get("filename", "")))
        if match is not None:
            selected[match.group(1)] = entry
    if set(selected) != {"arm64_v8a", "x86_64"}:
        return cached

    wheel_dir = app_dir / "wheels"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    synced: list[Path] = []
    pending: list[tuple[Path, Path]] = []
    try:
        for abi in ("arm64_v8a", "x86_64"):
            entry = selected[abi]
            filename = str(entry["filename"])
            url = str(entry["url"])
            digests = entry.get("digests")
            digest = str(digests.get("sha256", "")) if isinstance(digests, dict) else ""
            if not url.startswith("https://") or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"invalid accelerator wheel metadata for {filename}")
            destination = wheel_dir / filename
            if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest:
                synced.append(destination)
                continue
            with urllib.request.urlopen(url, timeout=20) as response:
                payload = response.read()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f"accelerator wheel digest mismatch for {filename}")
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(payload)
            pending.append((temporary, destination))
            synced.append(destination)
    except (KeyError, OSError, ValueError, urllib.error.URLError):
        for temporary, _destination in pending:
            temporary.unlink(missing_ok=True)
        return cached

    for temporary, destination in pending:
        temporary.replace(destination)

    requirement.write_text(f"luvatrix=={version}\n", encoding="utf-8")
    return tuple(synced)


def _cached_android_accelerator_wheels(app_dir: Path, *, version: str) -> tuple[Path, ...]:
    requirement = app_dir / "luvatrix-android-accel.txt"
    try:
        if requirement.read_text(encoding="utf-8") != f"luvatrix=={version}\n":
            return ()
    except OSError:
        return ()
    wheel_dir = app_dir / "wheels"
    normalized_version = str(version).replace("-", "_")
    selected: list[Path] = []
    for abi in ("arm64_v8a", "x86_64"):
        matches = tuple(
            wheel_dir.glob(f"luvatrix-{normalized_version}-cp314-cp314-android_*_{abi}.whl")
        )
        if len(matches) != 1:
            return ()
        selected.append(matches[0])
    return tuple(selected)


def _running_from_source_checkout() -> bool:
    return (Path(__file__).resolve().parents[3] / "pyproject.toml").is_file()


def _android_python_packages_for_app(app_dir: Path, *, exclude_dirs: Iterable[Path] = ()) -> tuple[str, ...]:
    packages = ["luvatrix", "luvatrix_core"]
    imported_modules = _imported_modules_for_app(app_dir, exclude_dirs=exclude_dirs)
    imports = {module.split(".", 1)[0] for module in imported_modules}
    for module in imported_modules:
        imports.update(_first_party_module_import_roots(module))
    for optional_pkg in ("luvatrix_ui", "luvatrix_plot"):
        if optional_pkg in imports:
            packages.append(optional_pkg)
    return tuple(packages)


def _imported_modules_for_app(app_dir: Path, *, exclude_dirs: Iterable[Path] = ()) -> set[str]:
    imports: set[str] = set()
    excluded = tuple(path.resolve() for path in exclude_dirs)
    for path in app_dir.rglob("*.py"):
        resolved = path.resolve()
        if "__pycache__" in path.parts or ".luvatrix" in path.parts:
            continue
        if any(_path_is_relative_to(resolved, root) for root in excluded):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def _first_party_module_import_roots(module_name: str) -> set[str]:
    package_name, _, relative_module = module_name.partition(".")
    if package_name not in {"luvatrix", "luvatrix_core"}:
        return set()
    package_dir = _python_package_dir(package_name)
    if relative_module:
        module_path = package_dir.joinpath(*relative_module.split("."))
        source_path = module_path.with_suffix(".py")
        if not source_path.is_file():
            source_path = module_path / "__init__.py"
    else:
        source_path = package_dir / "__init__.py"
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, SyntaxError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _make_android_app_ignore(project_dir: Path):
    pattern_ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".luvatrix")
    project = project_dir.resolve()

    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(pattern_ignore(directory, names))
        root = Path(directory).resolve()
        for name in names:
            if (root / name).resolve() == project:
                ignored.add(name)
        return ignored

    return _ignore


def _path_is_relative_to(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _python_package_dir(pkg_name: str) -> Path:
    repo_candidate = Path(__file__).resolve().parents[3] / pkg_name
    if repo_candidate.is_dir():
        return repo_candidate
    spec = importlib.util.find_spec(pkg_name)
    locations = getattr(spec, "submodule_search_locations", None) if spec is not None else None
    if locations:
        return Path(next(iter(locations))).resolve()
    if spec is not None and spec.origin:
        return Path(spec.origin).resolve().parent
    raise RuntimeError(f"Python package {pkg_name!r} was not found for Android asset sync")


def _write_android_app_bundle(app_dir: Path, *, py_dst: Path) -> None:
    package_dir = py_dst / "examples" / app_dir.name
    package_dir.mkdir(parents=True, exist_ok=True)
    (py_dst / "examples" / "__init__.py").write_text(
        "# Namespace marker for bundled Luvatrix examples.\n",
        encoding="utf-8",
    )
    (package_dir / "__init__.py").touch()
    app_toml = (app_dir / "app.toml").read_text(encoding="utf-8")
    app_main = (app_dir / "app_main.py").read_text(encoding="utf-8")
    (package_dir / "_luvatrix_bundle.py").write_text(
        f"APP_TOML = {app_toml!r}\n"
        f"APP_MAIN = {app_main!r}\n",
        encoding="utf-8",
    )


def force_stop_android_app(
    *,
    package_name: str = DEFAULT_ANDROID_PACKAGE,
    device_id: str | None = None,
) -> None:
    adb = shutil.which("adb")
    if adb is None:
        raise RuntimeError("adb not found on PATH")
    prefix = _adb_prefix(adb, device_id=device_id)
    subprocess.run(prefix + ["shell", "am", "force-stop", package_name], check=True, env=_android_subprocess_env())


def _adb_prefix(adb: str, *, device_id: str | None = None) -> list[str]:
    active = _connected_devices(adb)
    if device_id:
        if device_id not in active:
            raise RuntimeError(
                f"Android device {device_id!r} is not connected. "
                f"Connected devices: {', '.join(active) or 'none'}"
            )
        return [adb, "-s", device_id]
    if not active:
        raise RuntimeError(
            "No Android emulator/device is connected. Start an AVD first, then verify with `adb devices`."
        )
    if len(active) > 1:
        raise RuntimeError(
            "Multiple Android devices are connected; rerun with --android-device-id "
            f"one of: {', '.join(active)}"
        )
    return [adb, "-s", active[0]]


def _ensure_emulator_running(avd_name: str | None = None, *, timeout_s: float = 180.0) -> str:
    adb = shutil.which("adb")
    if adb is None:
        raise RuntimeError("adb not found on PATH")
    active = _connected_devices(adb)
    emulators = [device for device in active if device.startswith("emulator-")]
    if emulators:
        return emulators[0]

    emulator = _find_emulator_binary()
    avd = avd_name or _default_avd_name(emulator)
    print(f"[android] starting emulator AVD {avd!r}")
    subprocess.Popen(
        [
            str(emulator),
            "-avd",
            avd,
            "-no-snapshot-save",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_android_subprocess_env(),
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        emulators = [device for device in _connected_devices(adb) if device.startswith("emulator-")]
        if emulators:
            serial = emulators[0]
            boot = subprocess.run(
                [adb, "-s", serial, "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                check=False,
                env=_android_subprocess_env(),
            )
            if boot.stdout.strip() == "1":
                print(f"[android] emulator ready: {serial}")
                return serial
        time.sleep(2.0)
    raise RuntimeError(f"Timed out waiting for Android emulator AVD {avd!r} to boot")


def _connected_devices(adb: str) -> list[str]:
    devices = subprocess.run(
        [adb, "devices"],
        capture_output=True,
        text=True,
        check=False,
        env=_android_subprocess_env(),
    )
    if devices.returncode != 0:
        raise RuntimeError(f"adb devices failed:\n{devices.stderr or devices.stdout}")
    return [
        line.split()[0]
        for line in devices.stdout.splitlines()[1:]
        if line.strip().endswith("\tdevice") or " device" in line.strip()
    ]


def _default_avd_name(emulator: Path) -> str:
    avds = subprocess.run(
        [str(emulator), "-list-avds"],
        capture_output=True,
        text=True,
        check=False,
        env=_android_subprocess_env(),
    )
    names = [line.strip() for line in avds.stdout.splitlines() if line.strip()]
    if not names:
        raise RuntimeError("No Android AVDs found. Create one with avdmanager or Android Studio.")
    preferred = [name for name in names if "luvatrix" in name.lower()]
    return (preferred or names)[0]


def _find_emulator_binary() -> Path:
    found = shutil.which("emulator")
    if found:
        return Path(found)
    candidates: list[Path] = []
    env = _android_subprocess_env()
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = env.get(key)
        if value:
            candidates.append(Path(value).expanduser() / "emulator" / "emulator")
    candidates.extend(
        [
            Path("/opt/homebrew/share/android-commandlinetools/emulator/emulator"),
            Path.home() / "Library" / "Android" / "sdk" / "emulator" / "emulator",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Android emulator binary not found. Add the SDK emulator directory to PATH.")


def _android_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    home = env.get("ANDROID_HOME", "").strip()
    root = env.get("ANDROID_SDK_ROOT", "").strip()
    if home and root and Path(home).expanduser() != Path(root).expanduser():
        # Android Gradle Plugin rejects conflicting SDK injections. Prefer
        # ANDROID_HOME; ANDROID_SDK_ROOT is deprecated by current tooling.
        env.pop("ANDROID_SDK_ROOT", None)
    elif root and not home:
        env["ANDROID_HOME"] = root
        env.pop("ANDROID_SDK_ROOT", None)
    return env
