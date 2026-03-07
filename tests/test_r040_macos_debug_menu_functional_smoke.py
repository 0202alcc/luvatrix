from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "ops" / "ci" / "r040_macos_debug_menu_functional_smoke.py"
_SPEC = importlib.util.spec_from_file_location("r040_macos_debug_menu_functional_smoke", _SCRIPT_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load script spec: {_SCRIPT_PATH}")
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


class R040MacOSDebugMenuFunctionalSmokeTests(unittest.TestCase):
    def test_preflight_contains_required_checks(self) -> None:
        preflight = _MOD._collect_preflight()
        checks = preflight["checks"]
        ids = {item["id"] for item in checks}
        self.assertIn("appkit", ids)
        self.assertIn("pyobjc", ids)
        self.assertIn("quartz_api", ids)
        self.assertIn("vulkan_optional", ids)

    def test_action_smoke_executes_all_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _MOD._exercise_actions(Path(tmp))
            self.assertTrue(result["all_executed"])
            statuses = {item["status"] for item in result["results"]}
            self.assertEqual(statuses, {"EXECUTED"})


if __name__ == "__main__":
    unittest.main()
