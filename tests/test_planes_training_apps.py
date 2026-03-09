from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "examples" / "planes_v2"

APP_IDS = [
    "hello_plane",
    "coordinate_playground",
    "camera_overlay_basics",
    "multi_plane_layout",
    "scroll_and_pan_plane",
    "interactive_components",
    "sensor_status_dashboard",
    "input_sensor_overlay_logger",
    "debug_capture_workflow",
    "planes_v2_poc_plus",
]

REQUIRED_HEADINGS = [
    "## Objective",
    "## Concepts introduced",
    "## Files to inspect",
    "## Hands-on tasks",
    "## Expected outputs/artifacts",
    "## Validation checklist",
    "## Stretch challenge",
]


def test_planes_training_apps_closeout_matrix_contract() -> None:
    closeout_path = REPO_ROOT / ".gateflow" / "closeout" / "a-048_closeout.md"
    assert closeout_path.is_file(), "missing A-048 closeout packet"
    closeout = closeout_path.read_text(encoding="utf-8")
    assert "# Training Demonstration Evidence" in closeout
    for app_id in APP_IDS:
        assert app_id in closeout, f"missing closeout matrix entry for {app_id}"
        expected_artifact = f"examples/planes_v2/{app_id}/validation_artifact.json"
        assert expected_artifact in closeout, f"missing artifact reference for {app_id}"


def _run_validation(app_id: str) -> dict[str, object]:
    app_dir = APP_ROOT / app_id
    cmd = [sys.executable, str(app_dir / "app_main.py"), "--validate"]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    artifact_path = app_dir / "validation_artifact.json"
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def test_planes_training_apps_contract() -> None:
    for app_id in APP_IDS:
        app_dir = APP_ROOT / app_id
        assert app_dir.is_dir(), f"missing app directory: {app_dir}"
        assert (app_dir / "app.toml").is_file(), f"missing app.toml for {app_id}"
        assert (app_dir / "app_main.py").is_file(), f"missing app_main.py for {app_id}"
        assert (app_dir / "plane.json").is_file(), f"missing plane.json for {app_id}"
        readme_path = app_dir / "README.md"
        assert readme_path.is_file(), f"missing README.md for {app_id}"
        readme = readme_path.read_text(encoding="utf-8")
        for heading in REQUIRED_HEADINGS:
            assert heading in readme, f"missing README heading '{heading}' for {app_id}"


def test_planes_training_apps_runtime_and_determinism() -> None:
    for app_id in APP_IDS:
        first = _run_validation(app_id)
        second = _run_validation(app_id)
        assert first == second, f"nondeterministic artifact for {app_id}"
        assert first["app_id"] == app_id
        assert first["status"] == "PASS"
        assert first["artifact_version"] == "v2"
        assert first["all_checks_passed"] is True
        checks = first["interactive_checks"]
        assert isinstance(checks, dict)
        assert checks, f"no interactive checks recorded for {app_id}"
        assert all(bool(v) for v in checks.values()), f"failing interactive checks for {app_id}: {checks}"
        assert first["validation_command"].endswith("--validate")

    routes_payload = _run_validation("planes_v2_poc_plus")
    assert routes_payload["routes"] == ["/home", "/settings", "/analytics"]
    assert routes_payload["active_route_path"] == "/analytics"


def test_planes_training_apps_debug_workflow_contract() -> None:
    payload = _run_validation("debug_capture_workflow")
    required = {
        "screenshot_taken",
        "record_toggled",
        "replay_started",
        "frame_step_count",
        "perf_hud_toggled",
        "bundle_exported",
    }
    checks = payload["interactive_checks"]
    assert required.issubset(set(checks.keys()))
    assert all(bool(checks[k]) for k in required)
