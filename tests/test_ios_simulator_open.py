from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from luvatrix_core.platform.ios.runner import _open_simulator_app


def _completed(args: list[str], returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


class OpenSimulatorAppTests(unittest.TestCase):
    def test_opens_simulator_inside_selected_xcode_when_launch_services_misses_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            developer_dir = Path(td) / "Xcode-beta.app" / "Contents" / "Developer"
            simulator_app = developer_dir / "Applications" / "Simulator.app"
            simulator_app.mkdir(parents=True)
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                calls.append(list(args))
                if args[:2] == ["xcode-select", "-p"]:
                    return _completed(args, stdout=f"{developer_dir}\n")
                if args == ["open", "-a", "Simulator"]:
                    return _completed(args, returncode=1)
                return _completed(args)

            with patch("luvatrix_core.platform.ios.runner.subprocess.run", side_effect=fake_run):
                self.assertTrue(_open_simulator_app())

            self.assertIn(["open", str(simulator_app)], calls)

    def test_falls_back_to_launch_services_name(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            calls.append(list(args))
            if args[:2] == ["xcode-select", "-p"]:
                return _completed(args, returncode=2)
            return _completed(args)

        with patch("luvatrix_core.platform.ios.runner.subprocess.run", side_effect=fake_run):
            self.assertTrue(_open_simulator_app())

        self.assertEqual(calls[-1], ["open", "-a", "Simulator"])

    def test_missing_simulator_window_is_not_fatal(self) -> None:
        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            if args[:2] == ["xcode-select", "-p"]:
                return _completed(args, stdout="/nonexistent/Developer\n")
            return _completed(args, returncode=1)

        with patch("luvatrix_core.platform.ios.runner.subprocess.run", side_effect=fake_run):
            self.assertFalse(_open_simulator_app())


if __name__ == "__main__":
    unittest.main()
