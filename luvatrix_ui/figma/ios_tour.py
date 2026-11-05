"""Run a Figma app tour in the iOS Simulator and screenshot every capture step.

The host launches ``luvatrix run-app --render ios-simulator`` with the tour in
``SIMCTL_CHILD_*`` env vars, then watches the tour's ``status.json`` inside the
app's data container. At each capture it takes ``xcrun simctl io screenshot``
and writes the matching ``ack_<step>`` so the app moves on.

Output directory contents: ``NN_<capture>.png`` screenshots, ``console.log``
(run-app and simulator console), ``app_log.txt`` (the app's unified-log output),
and ``summary.json``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .tour import STATUS_FILE, TOUR_ACK_TIMEOUT_ENV, TOUR_ENV, TOUR_RUN_ENV, load_tour_steps
from luvatrix_core.platform.ios.bundle_id import ios_bundle_id

APP_PROCESS = "Luvatrix"
POLL_SECONDS = 0.25


def run_ios_tour(
    app_dir: str | Path,
    tour: str,
    out_dir: str | Path,
    *,
    simulator: str = "iPhone 17",
    native_project: str | Path | None = None,
    render_scale: float = 3.0,
    timeout: float = 900.0,
    settle: float = 0.75,
    ack_timeout: float = 60.0,
    keep_open: bool = False,
    reset_simulator: bool = False,
    run_id: str | None = None,
    run: Callable[..., Any] = subprocess.run,
    popen: Callable[..., Any] = subprocess.Popen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Returns 0 when the tour finished with every capture screenshotted, else 1."""
    steps = load_tour_steps(tour)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    run_id = run_id or uuid.uuid4().hex[:12]
    bundle_id = ios_bundle_id(app_dir)
    summary: dict[str, Any] = {"run": run_id, "simulator": simulator, "state": "starting", "captures": [], "error": None}

    udid = _simulator_udid(run, simulator)
    if udid is None:
        summary.update(state="no_simulator", error=f"simulator {simulator!r} not found; check `xcrun simctl list devices`")
        return _finish(out, summary)
    summary["udid"] = udid

    log_start = time.strftime("%Y-%m-%d %H:%M:%S")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env[f"SIMCTL_CHILD_{TOUR_ENV}"] = json.dumps(steps)
    env[f"SIMCTL_CHILD_{TOUR_RUN_ENV}"] = run_id
    env[f"SIMCTL_CHILD_{TOUR_ACK_TIMEOUT_ENV}"] = f"{ack_timeout:g}"
    cmd = [
        sys.executable,
        "-m",
        "main",
        "run-app",
        str(app_dir),
        "--render",
        "ios-simulator",
        "--simulator",
        simulator,
        "--render-scale",
        f"{render_scale:g}",
    ]
    if native_project is not None:
        cmd += ["--native-project", str(native_project)]

    if reset_simulator:
        # Terminating and even uninstalling the app is not enough to clear a
        # previous launch: the simulator retains that launch's environment per
        # bundle id across process death and reinstall, and keeps delivering it
        # to newly spawned processes, so the tour runs with a stale run id and
        # this harness never sees its own status. Erasing the device drops
        # every retained launch record. Shutdown failure just means the device
        # was already off; a failed erase means the device state is unknown,
        # so launching anyway would burn the whole timeout on a stale tour.
        print(f"[ios-tour] erasing simulator {simulator} ({udid}) for a clean launch", flush=True)
        run(["xcrun", "simctl", "shutdown", udid], capture_output=True)
        erased = run(["xcrun", "simctl", "erase", udid], capture_output=True, text=True)
        if erased.returncode != 0:
            detail = (erased.stderr or erased.stdout or "").strip()
            summary.update(state="reset_failed", error=f"simctl erase failed: {detail}")
            return _finish(out, summary)

    # Kill any stale instance (e.g. a kept-open app from a previous tour) before
    # run-app reinstalls and launches: an app killed by the install can be
    # auto-relaunched with the previous launch's retained environment, and the
    # env-carrying `simctl launch` then no-ops instead of delivering this run's
    # tour config.
    run(["xcrun", "simctl", "terminate", udid, bundle_id], capture_output=True)

    with open(out / "console.log", "w", buffering=1) as console:
        proc = popen(cmd, env=env, stdout=console, stderr=subprocess.STDOUT)
        container: Path | None = None
        pinned = False
        foreign_warned: str | None = None
        shot = 0
        done_steps: set[int] = set()
        deadline = clock() + timeout
        try:
            while True:
                if clock() >= deadline:
                    summary.update(state="timeout", error=f"tour did not finish within {timeout:g}s")
                    break
                # Re-resolve until this run's status shows up: before run-app reinstalls
                # the app, simctl still reports the previous install's data container.
                if not pinned:
                    container = _app_container(run, udid, bundle_id)
                raw = _read_status(container) if container else None
                status = raw if raw is not None and raw.get("run") == run_id else None
                if raw is not None and status is None:
                    foreign = str(raw.get("run") or "?")
                    if foreign != foreign_warned:
                        print(f"[ios-tour] ignoring status from run {foreign} (waiting for {run_id})", flush=True)
                        foreign_warned = foreign
                pinned = pinned or status is not None
                if status is not None and status.get("state") == "capture" and status.get("step") not in done_steps:
                    sleep(settle)
                    name = _safe_name(str(status.get("capture", "capture")))
                    file_name = f"{shot:02d}_{name}.png"
                    run(["xcrun", "simctl", "io", udid, "screenshot", str(out / file_name)], capture_output=True, check=True)
                    summary["captures"].append({"step": status["step"], "name": status.get("capture"), "frame": status.get("frame"), "file": file_name})
                    print(f"[ios-tour] captured {file_name} ({status.get('frame')})", flush=True)
                    shot += 1
                    done_steps.add(status["step"])
                    assert container is not None
                    (_status_dir(container) / f"ack_{status['step']}").write_text("ok")
                    continue
                if status is not None and status.get("state") in {"done", "error"}:
                    summary.update(state=status["state"], error=status.get("error"), timed_out=status.get("timed_out", []))
                    break
                code = proc.poll()
                if code is not None:
                    summary.update(state="app_exited", error=f"run-app exited with code {code} before the tour finished")
                    break
                sleep(POLL_SECONDS)
        finally:
            _write_app_log(run, udid, log_start, out)
            if keep_open:
                summary["kept_open"] = True
                _relaunch_for_user(run, udid, render_scale, bundle_id, out)
            else:
                run(["xcrun", "simctl", "terminate", udid, bundle_id], capture_output=True)
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
    return _finish(out, summary)


def _relaunch_for_user(run: Callable[..., Any], udid: str, render_scale: float, bundle_id: str, out: Path) -> None:
    """Relaunch the app detached, without tour env, and surface the simulator window.

    The tour instance may still be foregrounded, so the bare ``simctl launch``
    activates (or fresh-starts) the app without ``--console``: whatever survives
    is owned by the simulator, not by this exiting launcher. The verification
    screenshot records which app is actually on screen.
    """
    env = os.environ.copy()
    # Scrub the tour env with empty overrides rather than dropping the keys: the
    # simulator retains the last spawning launch's environment, so an omitted
    # key can leak a previous tour's config into the next launch.
    for key in (f"SIMCTL_CHILD_{TOUR_ENV}", f"SIMCTL_CHILD_{TOUR_RUN_ENV}", f"SIMCTL_CHILD_{TOUR_ACK_TIMEOUT_ENV}"):
        env[key] = ""
    env["SIMCTL_CHILD_LUVATRIX_IOS_RENDER_SCALE"] = f"{render_scale:.6g}"
    env["SIMCTL_CHILD_LUVATRIX_RENDER_MODE"] = os.environ.get("LUVATRIX_RENDER_MODE", "auto")
    run(["xcrun", "simctl", "launch", udid, bundle_id], capture_output=True, env=env)
    opened = run(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid], capture_output=True)
    if opened.returncode != 0:
        run(["open", "-a", "Simulator"], capture_output=True)
    run(["xcrun", "simctl", "io", udid, "screenshot", str(out / "kept_open.png")], capture_output=True)


def _finish(out: Path, summary: dict[str, Any]) -> int:
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    ok = summary["state"] == "done" and not summary.get("timed_out")
    print(f"[ios-tour] {summary['state']}: {len(summary['captures'])} screenshot(s) in {out}", flush=True)
    if summary.get("error"):
        print(f"[ios-tour] error: {summary['error']}", flush=True)
    return 0 if ok else 1


def _simulator_udid(run: Callable[..., Any], name: str) -> str | None:
    from luvatrix_core.platform.ios.runner import _find_simulator_udid

    result = run(["xcrun", "simctl", "list", "devices", "--json"], capture_output=True, text=True, check=True)
    return _find_simulator_udid(json.loads(result.stdout), name)


def _app_container(run: Callable[..., Any], udid: str, bundle_id: str) -> Path | None:
    result = run(["xcrun", "simctl", "get_app_container", udid, bundle_id, "data"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _status_dir(container: Path) -> Path:
    return container / "tmp" / "luvatrix_tour"


def _read_status(container: Path) -> dict[str, Any] | None:
    try:
        status = json.loads((_status_dir(container) / STATUS_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return status if isinstance(status, dict) else None


def _write_app_log(run: Callable[..., Any], udid: str, start: str, out: Path) -> None:
    # On iOS the app's Python stdout goes to syslog, so its output only reaches the unified log.
    cmd = ["xcrun", "simctl", "spawn", udid, "log", "show", "--style", "compact", "--start", start]
    result = run([*cmd, "--predicate", f'process == "{APP_PROCESS}"'], capture_output=True, text=True)
    (out / "app_log.txt").write_text(result.stdout or result.stderr or "")


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "capture"
