from __future__ import annotations

import argparse
import ctypes.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "artifacts" / "debug_menu" / "r039_smoke"


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
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
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

        return {
            "id": "quartz_api",
            "required": True,
            "status": "PASS",
            "detail": "Quartz import available",
            "module": "Quartz",
        }
    except Exception:
        pass
    try:
        import QuartzCore  # type: ignore  # noqa: F401

        return {
            "id": "quartz_api",
            "required": True,
            "status": "PASS",
            "detail": "QuartzCore fallback import available",
            "module": "QuartzCore",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "id": "quartz_api",
            "required": True,
            "status": "FAIL",
            "detail": f"{type(exc).__name__}: {exc}",
            "module": None,
        }


def _check_vulkan_status() -> dict[str, object]:
    loader = ctypes.util.find_library("vulkan")
    loader_found = bool(loader)
    try:
        import vulkan as vk  # type: ignore

        vk_version = getattr(vk, "__version__", "unknown")
        module_ok = True
        module_detail = f"python vulkan bindings available ({vk_version})"
    except Exception as exc:  # noqa: BLE001
        module_ok = False
        module_detail = f"{type(exc).__name__}: {exc}"
    status = "PASS" if loader_found or module_ok else "WARN"
    detail = (
        f"loader={'present' if loader_found else 'missing'}; "
        f"module={'present' if module_ok else 'missing'} ({module_detail})"
    )
    return {
        "id": "vulkan_optional",
        "required": False,
        "status": status,
        "detail": detail,
        "loader": loader or "",
    }


def _collect_preflight() -> dict[str, object]:
    checks = [
        _check_appkit(),
        _check_pyobjc_core(),
        _check_quartz_or_quartzcore(),
        _check_vulkan_status(),
    ]
    required = [item for item in checks if bool(item.get("required"))]
    required_ok = all(item["status"] == "PASS" for item in required)
    return {
        "host_platform": sys.platform,
        "checks": checks,
        "required_checks_passed": required_ok,
        "summary": "ready" if required_ok else "missing_required_runtime_prereqs",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run R-039 macOS menu smoke with deterministic preflight")
    parser.add_argument("--skip-runs", action="store_true", help="only emit preflight manifest without run-app commands")
    parser.add_argument("--output-dir", default=str(OUT_DIR), help="artifact output directory")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = (ROOT / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    preflight = _collect_preflight()
    results: list[dict[str, object]] = []
    if not args.skip_runs and bool(preflight["required_checks_passed"]):
        results = [
            _run("planes_v2_poc", "examples/app_protocol/planes_v2_poc", out_dir),
            _run("input_sensor_logger", "examples/app_protocol/input_sensor_logger", out_dir),
        ]
    elif not args.skip_runs:
        results = [
            {
                "name": "planes_v2_poc",
                "status": "SKIPPED",
                "reason": "required preflight checks failed",
                "return_code": 1,
            },
            {
                "name": "input_sensor_logger",
                "status": "SKIPPED",
                "reason": "required preflight checks failed",
                "return_code": 1,
            },
        ]
    payload = {
        "milestone_id": "R-039",
        "generated_at_epoch_sec": int(time.time()),
        "preflight": preflight,
        "runs": results,
        "all_passed": bool(preflight["required_checks_passed"])
        and all(int(item["return_code"]) == 0 for item in results),
    }
    (out_dir / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
