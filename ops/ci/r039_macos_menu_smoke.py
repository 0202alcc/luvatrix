from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "artifacts" / "debug_menu" / "r039_smoke"


def _run(name: str, app_dir: str) -> dict[str, object]:
    log_path = OUT_DIR / f"{name}.log"
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
        "log": str(log_path.relative_to(ROOT)),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = [
        _run("planes_v2_poc", "examples/app_protocol/planes_v2_poc"),
        _run("input_sensor_logger", "examples/app_protocol/input_sensor_logger"),
    ]
    payload = {
        "milestone_id": "R-039",
        "generated_at_epoch_sec": int(time.time()),
        "runs": results,
        "all_passed": all(int(item["return_code"]) == 0 for item in results),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
