from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tomllib


DEFAULT_ANDROID_PACKAGE = "com.luvatrix.app"


def android_project_dir(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    return root / "android"


def build_android_debug_apk(project_dir: Path | None = None) -> Path:
    project = project_dir or android_project_dir()
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
    project = project_dir or android_project_dir()
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
    import_probe: bool,
    render_scale: float,
    render_mode: str,
    target_fps: int | None,
    present_fps: int | None,
    low_latency_mode: bool,
) -> None:
    project = android_project_dir()
    write_android_launch_config(
        app_dir,
        project_dir=project,
        render_scale=render_scale,
        render_mode=render_mode,
        target_fps=target_fps,
        present_fps=present_fps,
        low_latency_mode=low_latency_mode,
    )
    sync = project / "scripts" / "sync_python_assets.sh"
    if not sync.exists():
        raise RuntimeError(f"Android Python asset sync script not found at {sync}")
    env = _android_subprocess_env()
    subprocess.run(["bash", str(sync), str(app_dir)], cwd=project.parent, check=True, env=env)
    apk = build_android_debug_apk(project)
    adb = shutil.which("adb")
    if adb is None:
        raise RuntimeError("adb not found on PATH")
    prefix = _adb_prefix(adb, device_id=device_id)
    subprocess.run(prefix + ["install", "-r", str(apk)], check=True, env=_android_subprocess_env())
    launch_android_app(package_name=package_name, device_id=device_id, import_probe=import_probe)


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
