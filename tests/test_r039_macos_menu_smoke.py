from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "ops" / "ci" / "r039_macos_menu_smoke.py"
_SPEC = importlib.util.spec_from_file_location("r039_macos_menu_smoke", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load script spec: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


class R039MacOSMenuSmokeTests(unittest.TestCase):
    def test_preflight_contains_required_checks(self) -> None:
        preflight = _MOD._collect_preflight()
        checks = preflight["checks"]
        ids = {item["id"] for item in checks}
        self.assertIn("appkit", ids)
        self.assertIn("pyobjc", ids)
        self.assertIn("quartz_api", ids)
        self.assertIn("vulkan_optional", ids)
        required = {item["id"]: item["required"] for item in checks}
        self.assertTrue(required["appkit"])
        self.assertTrue(required["pyobjc"])
        self.assertTrue(required["quartz_api"])
        self.assertFalse(required["vulkan_optional"])

    def test_optional_vulkan_status_shape(self) -> None:
        status = _MOD._check_vulkan_status()
        self.assertEqual(status["id"], "vulkan_optional")
        self.assertFalse(status["required"])
        self.assertIn(status["status"], {"PASS", "WARN"})
        self.assertIn("loader=", str(status["detail"]))


if __name__ == "__main__":
    unittest.main()
