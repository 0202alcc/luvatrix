from __future__ import annotations

import argparse
import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from luvatrix_core.platform.macos.vulkan_backend import MoltenVKMacOSBackend
from luvatrix_core.platform.macos.window_system import MacOSWindowHandle


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "artifacts" / "debug_menu" / "r040_smoke"


class _FakeWindowSystem:
    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        use_metal_layer: bool = True,
        preserve_aspect_ratio: bool = False,
        menu_config=None,
    ) -> MacOSWindowHandle:
        _ = (width, height, title, use_metal_layer, preserve_aspect_ratio, menu_config)

        class _Layer:
            pass

        return MacOSWindowHandle(window=object(), layer=_Layer())

    def destroy_window(self, handle: MacOSWindowHandle) -> None:
        _ = handle

    def pump_events(self) -> None:
        return

    def is_window_open(self, handle: MacOSWindowHandle) -> bool:
        _ = handle
        return True


def _run(name: str, app_dir: str, out_dir: Path) -> dict[str, object]:
    log_path = out_dir / f"{name}.log"
    cmd = [
        "uv",
        "run",
        "python",
        "main.py",
        "run-app",
        app_dir,
        "--render",
        "macos",
        "--ticks",
        "120",
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", ".")
    started = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, check=False)
    duration = time.time() - started
    log_path.write_text(proc.stdout + ("\n" if proc.stdout else "") + proc.stderr, encoding="utf-8")
    return {
        "name": name,
        "command": " ".join(cmd),
        "return_code": proc.returncode,
        "duration_sec": round(duration, 3),
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "log": str(log_path.relative_to(ROOT)),
    }


def _check_appkit() -> dict[str, object]:
    try:
        import AppKit  # type: ignore  # noqa: F401

        return {"id": "appkit", "required": True, "status": "PASS", "detail": "AppKit import available"}
    except Exception as exc:  # noqa: BLE001
        return {"id": "appkit", "required": True, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"}


def _check_pyobjc_core() -> dict[str, object]:
    try:
        import objc  # type: ignore  # noqa: F401

        return {"id": "pyobjc", "required": True, "status": "PASS", "detail": "objc runtime import available"}
    except Exception as exc:  # noqa: BLE001
        return {"id": "pyobjc", "required": True, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"}


def _check_quartz_or_quartzcore() -> dict[str, object]:
    try:
        import Quartz  # type: ignore  # noqa: F401

        return {"id": "quartz_api", "required": True, "status": "PASS", "detail": "Quartz import available"}
    except Exception:
        pass
    try:
        import QuartzCore  # type: ignore  # noqa: F401

        return {"id": "quartz_api", "required": True, "status": "PASS", "detail": "QuartzCore fallback import available"}
    except Exception as exc:  # noqa: BLE001
        return {"id": "quartz_api", "required": True, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"}


def _check_vulkan_status() -> dict[str, object]:
    loader = ctypes.util.find_library("vulkan")
    loader_found = bool(loader)
    try:
        import vulkan as vk  # type: ignore

        module_ok = True
        module_detail = f"python vulkan bindings available ({getattr(vk, '__version__', 'unknown')})"
    except Exception as exc:  # noqa: BLE001
        module_ok = False
        module_detail = f"{type(exc).__name__}: {exc}"
    return {
        "id": "vulkan_optional",
        "required": False,
        "status": "PASS" if loader_found or module_ok else "WARN",
        "detail": f"loader={'present' if loader_found else 'missing'}; module={'present' if module_ok else 'missing'} ({module_detail})",
    }


def _collect_preflight() -> dict[str, object]:
    checks = [_check_appkit(), _check_pyobjc_core(), _check_quartz_or_quartzcore(), _check_vulkan_status()]
    required_checks_passed = all(item["status"] == "PASS" for item in checks if bool(item["required"]))
    return {
        "host_platform": sys.platform,
        "checks": checks,
        "required_checks_passed": required_checks_passed,
        "summary": "ready" if required_checks_passed else "missing_required_runtime_prereqs",
    }


def _exercise_actions(out_dir: Path) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp) / "runtime"
        backend = MoltenVKMacOSBackend(window_system=_FakeWindowSystem())
        profile = {
            "supported": True,
            "enable_default_debug_root": True,
            "declared_capabilities": ["debug.root.default"],
            "host_os": "macos",
        }
        backend.configure_debug_menu(app_id="r040.smoke", profile=profile, artifact_dir=artifact_dir)
        action_order = [
            "debug.menu.capture.screenshot",
            "debug.menu.capture.record.toggle",
            "debug.menu.capture.record.toggle",
            "debug.menu.overlay.toggle",
            "debug.menu.replay.start",
            "debug.menu.frame.step",
            "debug.menu.perf.hud.toggle",
            "debug.menu.bundle.export",
        ]
        results: list[dict[str, str]] = []
        for action_id in action_order:
            result = backend.dispatch_debug_menu_action(action_id)
            results.append({"action_id": action_id, "status": result.status})
        copied_dir = out_dir / "runtime"
        copied_dir.mkdir(parents=True, exist_ok=True)
        for path in artifact_dir.rglob("*"):
            if path.is_file():
                rel = path.relative_to(artifact_dir)
                target = copied_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
    return {
        "results": results,
        "all_executed": all(item["status"] == "EXECUTED" for item in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R-040 macOS debug menu functional smoke")
    parser.add_argument("--skip-runs", action="store_true", help="skip run-app commands")
    parser.add_argument("--output-dir", default=str(OUT_DIR), help="artifact output directory")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = (ROOT / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    preflight = _collect_preflight()
    action_smoke = _exercise_actions(out_dir)
    runs: list[dict[str, object]]
    if not args.skip_runs and bool(preflight["required_checks_passed"]):
        runs = [
            _run("planes_v2_poc", "examples/app_protocol/planes_v2_poc", out_dir),
            _run("input_sensor_logger", "examples/app_protocol/input_sensor_logger", out_dir),
        ]
    elif args.skip_runs:
        runs = []
    else:
        runs = [
            {"name": "planes_v2_poc", "status": "SKIPPED", "return_code": 1, "reason": "required preflight checks failed"},
            {"name": "input_sensor_logger", "status": "SKIPPED", "return_code": 1, "reason": "required preflight checks failed"},
        ]

    payload = {
        "milestone_id": "R-040",
        "generated_at_epoch_sec": int(time.time()),
        "preflight": preflight,
        "action_smoke": action_smoke,
        "runs": runs,
        "all_passed": bool(preflight["required_checks_passed"])
        and bool(action_smoke["all_executed"])
        and all(int(item.get("return_code", 0)) == 0 for item in runs),
    }
    (out_dir / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
