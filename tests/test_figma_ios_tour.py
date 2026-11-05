from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from luvatrix_ui.figma.ios_tour import run_ios_tour

UDID = "UDID-17"
BUNDLE = "com.luvatrix.app"


class _FakeSimulator:
    """Stands in for xcrun simctl and the app: emits tour statuses and waits for acks."""

    def __init__(self, root: Path, captures: list[tuple[str, str]], *, final: str = "done", exit_early: bool = False, bundle: str = BUNDLE) -> None:
        self.bundle = bundle
        self.container = root / "container"
        self.status_dir = self.container / "tmp" / "luvatrix_tour"
        self.captures = captures
        self.final = final
        self.exit_early = exit_early
        self.commands: list[list[str]] = []
        self.env: dict[str, str] = {}
        self.launch_cmd: list[str] = []
        self.log_show_cmd: list[str] = []
        self.launch_commands: list[tuple[list[str], dict[str, str] | None]] = []
        self.open_commands: list[list[str]] = []
        self.fail_device_open = False
        self.previous_install: Path | None = None
        self.returncode: int | None = None
        self.terminated = False
        self.terminate_calls: list[list[str]] = []
        self.terminated_before_launch = False
        self.foreign_run: str | None = None
        self.step = 0
        self.ticks = 0
        self.now = 0.0

    def run(self, cmd, **_kwargs):
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        if cmd[:4] == ["xcrun", "simctl", "list", "devices"]:
            devices = {"devices": {"iOS": [{"name": "iPhone 17", "udid": UDID, "state": "Booted", "isAvailable": True}]}}
            return SimpleNamespace(returncode=0, stdout=json.dumps(devices), stderr="")
        if cmd[:3] == ["xcrun", "simctl", "get_app_container"]:
            assert cmd[3:] == [UDID, self.bundle, "data"]
            if not self.container.exists():
                if self.previous_install is not None:
                    return SimpleNamespace(returncode=0, stdout=f"{self.previous_install}\n", stderr="")
                return SimpleNamespace(returncode=2, stdout="", stderr="not installed")
            return SimpleNamespace(returncode=0, stdout=f"{self.container}\n", stderr="")
        if cmd[:4] == ["xcrun", "simctl", "io", UDID]:
            Path(cmd[-1]).write_bytes(b"\x89PNG fake")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["xcrun", "simctl", "terminate"]:
            self.terminated = True
            self.terminate_calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:3] == ["xcrun", "simctl", "launch"]:
            assert cmd[3:] == [UDID, self.bundle]
            self.launch_commands.append((cmd, _kwargs.get("env")))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:1] == ["open"]:
            if self.fail_device_open and "-CurrentDeviceUDID" in cmd:
                self.open_commands.append(cmd)
                return SimpleNamespace(returncode=1, stdout="", stderr="no such device")
            self.open_commands.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[:6] == ["xcrun", "simctl", "spawn", UDID, "log", "show"]:
            self.log_show_cmd = cmd
            return SimpleNamespace(returncode=0, stdout="Luvatrix: [figma-tour] run=run-xyz\n", stderr="")
        raise AssertionError(f"unexpected command {cmd}")

    def popen(self, cmd, *, env, stdout, stderr, **_kwargs):
        self.launch_cmd = [str(c) for c in cmd]
        self.env = env
        self.terminated_before_launch = self.terminated
        stdout.write("[ios] launching com.luvatrix.app\n")
        return self

    # subprocess.Popen surface
    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        _ = timeout
        return self.returncode

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.ticks += 1
        if self.ticks == 3:
            self.container.mkdir(parents=True, exist_ok=True)
        if self.ticks < 5:
            return
        if self.exit_early:
            self.returncode = 1
            return
        self._advance_app()

    def _advance_app(self) -> None:
        run = self.foreign_run or self.env["SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR_RUN"]
        self.status_dir.mkdir(parents=True, exist_ok=True)
        status_path = self.status_dir / "status.json"
        if self.step < len(self.captures):
            if (self.status_dir / f"ack_{self.step}").exists():
                self.step += 1
                return
            name, frame = self.captures[self.step]
            status = {"run": run, "step": self.step, "state": "capture", "capture": name, "frame": frame, "timed_out": []}
        else:
            status = {"run": run, "step": self.step, "state": self.final, "frame": "Home", "timed_out": []}
            if self.final == "error":
                status["error"] = "no tappable layer named 'Nope'"
        status_path.write_text(json.dumps(status))


def _run(tmp_path: Path, sim: _FakeSimulator, **kwargs) -> int:
    tour = json.dumps([{"capture": name} for name, _ in sim.captures])
    return run_ios_tour(
        tmp_path / "app",
        tour,
        tmp_path / "out",
        simulator="iPhone 17",
        native_project=tmp_path / "app" / "ios",
        render_scale=3.0,
        run_id="run-xyz",
        run=sim.run,
        popen=sim.popen,
        sleep=sim.sleep,
        clock=sim.clock,
        **kwargs,
    )


def test_ios_tour_screenshots_each_capture_and_writes_a_summary(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome"), ("home", "Home")])

    code = _run(tmp_path, sim)

    out = tmp_path / "out"
    assert code == 0
    assert (out / "00_welcome.png").read_bytes().startswith(b"\x89PNG")
    assert (out / "01_home.png").exists()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["state"] == "done"
    assert [(c["name"], c["frame"], c["file"]) for c in summary["captures"]] == [
        ("welcome", "Welcome", "00_welcome.png"),
        ("home", "Home", "01_home.png"),
    ]
    assert "[ios] launching" in (out / "console.log").read_text()
    assert "[figma-tour] run=run-xyz" in (out / "app_log.txt").read_text()
    assert 'process == "Luvatrix"' in sim.log_show_cmd
    assert sim.terminated


def test_ios_tour_launches_run_app_with_the_tour_in_the_simulator_env(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")])

    _run(tmp_path, sim)

    args = sim.launch_cmd[sim.launch_cmd.index("run-app") :]
    assert args == [
        "run-app",
        str(tmp_path / "app"),
        "--render",
        "ios-simulator",
        "--simulator",
        "iPhone 17",
        "--render-scale",
        "3",
        "--native-project",
        str(tmp_path / "app" / "ios"),
    ]
    assert json.loads(sim.env["SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR"]) == [{"capture": "welcome"}]
    assert sim.env["SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR_RUN"] == "run-xyz"
    assert sim.env["PYTHONUNBUFFERED"] == "1"


def test_ios_tour_ignores_status_from_a_previous_run(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")])
    sim.status_dir.mkdir(parents=True)
    (sim.status_dir / "status.json").write_text(json.dumps({"run": "old", "step": 0, "state": "done"}))

    code = _run(tmp_path, sim)

    assert code == 0
    assert (tmp_path / "out" / "00_welcome.png").exists()


def test_ios_tour_follows_the_new_container_when_run_app_reinstalls_the_app(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")])
    sim.previous_install = tmp_path / "old-container"
    (sim.previous_install / "tmp" / "luvatrix_tour").mkdir(parents=True)

    code = _run(tmp_path, sim)

    assert code == 0
    assert (tmp_path / "out" / "00_welcome.png").exists()
    assert (sim.status_dir / "ack_0").exists()


def test_ios_tour_fails_when_the_app_reports_an_error(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")], final="error")

    code = _run(tmp_path, sim)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 1
    assert summary["state"] == "error"
    assert "Nope" in summary["error"]


def test_ios_tour_fails_when_run_app_exits_before_the_tour_finishes(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")], exit_early=True)

    code = _run(tmp_path, sim)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 1
    assert summary["state"] == "app_exited"
    assert "1" in summary["error"]


def test_ios_tour_times_out_and_stops_the_app(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")])
    sim.sleep = lambda seconds: setattr(sim, "now", sim.now + seconds)  # app never starts

    code = _run(tmp_path, sim, timeout=5.0)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 1
    assert summary["state"] == "timeout"
    assert sim.returncode is not None
    assert sim.terminated
    assert "[figma-tour]" in (tmp_path / "out" / "app_log.txt").read_text()


def test_ios_tour_rejects_a_malformed_tour_before_launching(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [])

    with pytest.raises(ValueError):
        run_ios_tour(tmp_path / "app", '[{"jump": 1}]', tmp_path / "out", run=sim.run, popen=sim.popen, sleep=sim.sleep, clock=sim.clock)
    assert sim.launch_cmd == []


def test_ios_tour_keep_open_relaunches_fresh_and_opens_the_simulator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sim = _FakeSimulator(tmp_path, [("sign_in", "Sign In")])
    monkeypatch.setenv("SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR", "leaked")
    monkeypatch.setenv("LUVATRIX_RENDER_MODE", "matrix")

    code = _run(tmp_path, sim, keep_open=True)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 0
    assert summary["state"] == "done"
    assert summary["kept_open"] is True
    # The tour app instance is not terminated at the end; only the console
    # parent is. The single terminate is the pre-launch stale-instance sweep.
    assert sim.terminate_calls == [["xcrun", "simctl", "terminate", UDID, BUNDLE]]
    assert sim.returncode is not None
    # Detached relaunch: bare simctl launch, no --console, with the render env
    # the runner normally sets and the tour env scrubbed to empty values (the
    # simulator retains the last spawning launch's environment, so merely
    # dropping the keys would leak this tour's config into the next launch).
    assert len(sim.launch_commands) == 1
    launch_cmd, launch_env = sim.launch_commands[0]
    assert launch_cmd == ["xcrun", "simctl", "launch", UDID, BUNDLE]
    assert launch_env is not None
    assert launch_env["SIMCTL_CHILD_LUVATRIX_IOS_RENDER_SCALE"] == "3"
    assert launch_env["SIMCTL_CHILD_LUVATRIX_RENDER_MODE"] == "matrix"
    assert launch_env["SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR"] == ""
    assert launch_env["SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR_RUN"] == ""
    assert launch_env["SIMCTL_CHILD_LUVATRIX_FIGMA_TOUR_ACK_TIMEOUT"] == ""
    assert sim.open_commands == [["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", UDID]]
    # The artifact proves which app ended up on screen.
    assert (tmp_path / "out" / "kept_open.png").read_bytes().startswith(b"\x89PNG")


def test_ios_tour_keep_open_falls_back_to_plain_simulator_open(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("sign_in", "Sign In")])
    sim.fail_device_open = True

    _run(tmp_path, sim, keep_open=True)

    assert sim.open_commands == [
        ["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", UDID],
        ["open", "-a", "Simulator"],
    ]


def test_ios_tour_keep_open_relaunches_even_when_the_app_exited_early(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("sign_in", "Sign In")], exit_early=True)

    code = _run(tmp_path, sim, keep_open=True)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 1
    assert summary["state"] == "app_exited"
    assert summary["kept_open"] is True
    assert len(sim.launch_commands) == 1
    assert sim.terminate_calls == [["xcrun", "simctl", "terminate", UDID, BUNDLE]]


def test_ios_tour_without_keep_open_terminates_and_never_relaunches(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("sign_in", "Sign In")])

    code = _run(tmp_path, sim)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 0
    assert "kept_open" not in summary
    assert sim.terminate_calls == [
        ["xcrun", "simctl", "terminate", UDID, BUNDLE],
        ["xcrun", "simctl", "terminate", UDID, BUNDLE],
    ]
    assert sim.launch_commands == []
    assert sim.open_commands == []
    assert not (tmp_path / "out" / "kept_open.png").exists()


def test_ios_tour_resolves_the_bundle_id_from_the_app_dir(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "app.toml").write_text('app_id = "figma.nomic_app"\n', encoding="utf-8")
    sim = _FakeSimulator(tmp_path, [("sign_in", "Sign In")], bundle="com.luvatrix.app.nomic-app")

    code = _run(tmp_path, sim, keep_open=True)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 0
    assert summary["state"] == "done"
    assert summary["kept_open"] is True
    assert sim.terminate_calls == [["xcrun", "simctl", "terminate", UDID, "com.luvatrix.app.nomic-app"]]
    launch_cmd, _ = sim.launch_commands[0]
    assert launch_cmd == ["xcrun", "simctl", "launch", UDID, "com.luvatrix.app.nomic-app"]


def test_ios_tour_keeps_the_legacy_bundle_id_without_app_id(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("sign_in", "Sign In")], bundle=BUNDLE)

    code = _run(tmp_path, sim)

    assert code == 0
    assert sim.terminated


def test_ios_tour_terminates_a_stale_app_before_launching_run_app(tmp_path: Path) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")])

    code = _run(tmp_path, sim)

    # A kept-open instance from a previous tour must be terminated before
    # run-app starts: the simulator can otherwise relaunch it with the previous
    # launch's retained environment and this run's tour config never lands.
    assert code == 0
    assert sim.terminated_before_launch
    assert sim.terminate_calls[0] == ["xcrun", "simctl", "terminate", UDID, BUNDLE]


def test_ios_tour_warns_when_only_a_stale_run_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sim = _FakeSimulator(tmp_path, [("welcome", "Welcome")])
    sim.foreign_run = "old-run"

    code = _run(tmp_path, sim, timeout=5.0)

    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert code == 1
    assert summary["state"] == "timeout"
    out = capsys.readouterr().out
    assert out.count("ignoring status from run old-run") == 1
