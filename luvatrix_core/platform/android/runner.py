from __future__ import annotations

import ast
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import time
import tomllib

from luvatrix_core.scaffold import resolve_native_project_dir


DEFAULT_ANDROID_PACKAGE = "com.luvatrix.app"


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
    render_scale: float = 1.0,
    render_mode: str = "auto",
    target_fps: int | None = None,
    present_fps: int | None = None,
    low_latency_mode: bool = True,
) -> Path:
    project = (project_dir or android_project_dir()).resolve()
    dest = project / "app" / "src" / "main" / "assets" / "luvatrix_launch_config.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    display = _read_app_display_config(app_dir)
    data = {
        "app_dir": "luvatrix_app",
        "source_app_dir": str(app_dir),
        "render_scale": float(render_scale),
        "render_mode": render_mode,
        "target_fps": target_fps,
        "present_fps": present_fps,
        "low_latency_mode": bool(low_latency_mode),
    }
    data.update(display)
    dest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest


def _read_app_display_config(app_dir: Path) -> dict[str, int]:
    manifest = app_dir / "app.toml"
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}
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
    py_dst = project_dir / "app" / "src" / "main" / "python"
    py_dst.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")

    all_pkg_names = ("luvatrix", "luvatrix_core", "luvatrix_ui", "luvatrix_plot")
    pkg_names = _android_python_packages_for_app(app_dir)
    for stale_pkg in set(all_pkg_names) - set(pkg_names):
        stale_dst = py_dst / stale_pkg
        if stale_dst.exists():
            shutil.rmtree(stale_dst)

    for pkg_name in pkg_names:
        src = _python_package_dir(pkg_name)
        dst = py_dst / pkg_name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=ignore)

    for rel in ("examples", "luvatrix_app"):
        dst = py_dst / rel
        if dst.exists():
            shutil.rmtree(dst)
    shutil.copytree(app_dir, py_dst / "luvatrix_app", ignore=ignore)
    (py_dst / "luvatrix_app" / "__init__.py").touch()
    _write_android_app_bundle(app_dir, py_dst=py_dst)

    config = project_dir / "app" / "src" / "main" / "assets" / "luvatrix_launch_config.json"
    if config.exists():
        shutil.copy2(config, py_dst / "luvatrix_launch_config.json")
    print(f"[android] synced Python assets for {app_dir}")


def _android_python_packages_for_app(app_dir: Path) -> tuple[str, ...]:
    packages = ["luvatrix", "luvatrix_core"]
    imports = _top_level_imports_for_app(app_dir)
    for optional_pkg in ("luvatrix_ui", "luvatrix_plot"):
        if optional_pkg in imports:
            packages.append(optional_pkg)
    return tuple(packages)


def _top_level_imports_for_app(app_dir: Path) -> set[str]:
    imports: set[str] = set()
    for path in app_dir.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
    return imports


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
