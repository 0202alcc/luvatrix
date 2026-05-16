from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


class AccelBackendTests(unittest.TestCase):
    def test_accel_imports_when_torch_is_unavailable(self) -> None:
        code = r'''
import builtins
real_import = builtins.__import__
def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch."):
        raise ImportError("blocked torch for android test")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = blocked_import
from luvatrix_core import accel
from luvatrix_core.platform.frame_pipeline import PresentationMode
assert accel.BACKEND in ("numpy", "pure"), accel.BACKEND
assert accel.zeros((1, 1, 4)).shape == (1, 1, 4)
assert PresentationMode.STRETCH.value == "stretch"
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_full_suite_imports_without_torch(self) -> None:
        code = r'''
import builtins
real_import = builtins.__import__
def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch."):
        raise ImportError("blocked torch for android test")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = blocked_import
import examples.full_suite_interactive.app_main as app
assert app.FullSuiteInteractiveApp is not None
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
