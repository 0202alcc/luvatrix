from __future__ import annotations

import subprocess
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from luvatrix_core.platform.ios.runner import _open_simulator_app

UDID = "17468E9B-9DDF-450A-9E10-8D5A2E07B4AF"


def _completed(args: list[str], returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


def _fake_run(
    developer_dir: Path | None,
    calls: list[list[str]],
    fails: Callable[[list[str]], bool] = lambda args: False,
):
    def run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[:2] == ["xcode-select", "-p"]:
            if developer_dir is None:
                return _completed(args, returncode=2)
            return _completed(args, stdout=f"{developer_dir}\n")
        return _completed(args, returncode=1 if fails(list(args)) else 0)

    return run


class OpenSimulatorAppTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.xcode = Path(tmp.name) / "Xcode.app"
        self.developer_dir = self.xcode / "Contents" / "Developer"
        self.developer_dir.mkdir(parents=True)

    def _open(self, developer_dir: Path | None, fails=lambda args: False) -> tuple[bool, list[list[str]]]:
        calls: list[list[str]] = []
        with patch(
            "luvatrix_core.platform.ios.runner.subprocess.run",
            side_effect=_fake_run(developer_dir, calls, fails),
        ):
            opened = _open_simulator_app(UDID)
        return opened, [c for c in calls if c[:2] != ["xcode-select", "-p"]]

    def test_opens_selected_xcode_simulator_app_on_the_booted_device(self) -> None:
        simulator_app = self.developer_dir / "Applications" / "Simulator.app"
        simulator_app.mkdir(parents=True)

        opened, calls = self._open(self.developer_dir)

        self.assertTrue(opened)
        self.assertEqual(calls, [["open", str(simulator_app), "--args", "-CurrentDeviceUDID", UDID]])

    def test_xcode_27_opens_the_device_in_device_hub(self) -> None:
        (self.xcode / "Contents" / "Applications" / "DeviceHub.app").mkdir(parents=True)

        opened, calls = self._open(self.developer_dir)

        self.assertTrue(opened)
        self.assertEqual(calls, [["open", f"devices://device/open?id={UDID}"]])

    def test_device_hub_opens_directly_when_its_url_scheme_fails(self) -> None:
        device_hub = self.xcode / "Contents" / "Applications" / "DeviceHub.app"
        device_hub.mkdir(parents=True)

        opened, calls = self._open(self.developer_dir, fails=lambda args: args[1].startswith("devices://"))

        self.assertTrue(opened)
        self.assertEqual(calls[-1], ["open", str(device_hub)])

    def test_falls_back_to_launch_services_names(self) -> None:
        opened, calls = self._open(None, fails=lambda args: args == ["open", "-a", "Simulator"])

        self.assertTrue(opened)
        self.assertEqual(calls, [["open", "-a", "Simulator"], ["open", "-a", "Device Hub"]])

    def test_missing_simulator_window_is_not_fatal(self) -> None:
        opened, _ = self._open(self.developer_dir, fails=lambda args: True)

        self.assertFalse(opened)


if __name__ == "__main__":
    unittest.main()
