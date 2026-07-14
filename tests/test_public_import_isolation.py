from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PublicImportIsolationTests(unittest.TestCase):
    def _run_import_probe(self, source: str) -> dict[str, object]:
        script = textwrap.dedent(
            f"""
            import json
            import sys

            {source}

            print(json.dumps({{
                "modules": sorted(sys.modules),
            }}))
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def assertModulesNotLoaded(self, modules: list[str], forbidden_prefixes: tuple[str, ...]) -> None:
        loaded_prefixes = [
            prefix
            for prefix in forbidden_prefixes
            if any(name == prefix or name.startswith(f"{prefix}.") for name in modules)
        ]
        self.assertEqual(loaded_prefixes, [], f"unexpected eager imports: {loaded_prefixes}")

    def test_app_and_text_wrapping_imports_stay_android_launch_lightweight(self) -> None:
        result = self._run_import_probe(
            "from luvatrix.app import App, TextWrapping, layout_text, prepare_text"
        )

        self.assertModulesNotLoaded(
            result["modules"],
            (
                "PIL",
                "numpy",
                "torch",
                "luvatrix_core.accel",
                "luvatrix_core.core.app_runtime",
                "luvatrix_core.core.scene_graph",
                "luvatrix_core.core.sensor_manager",
                "luvatrix_core.core.window_matrix",
                "luvatrix_ui.planes_protocol",
                "luvatrix_ui.planes_runtime",
                "luvatrix_ui.planning",
                "luvatrix_ui.table",
                "luvatrix_ui.text.component",
                "luvatrix_ui.text.renderer",
                "luvatrix_ui.ui_ir",
            ),
        )

    def test_public_text_wrapping_import_does_not_load_rendering_or_ui_bundles(self) -> None:
        result = self._run_import_probe(
            "from luvatrix_ui.text import TextWrapping, layout_text, prepare_text"
        )

        self.assertModulesNotLoaded(
            result["modules"],
            (
                "PIL",
                "luvatrix_ui.planes_protocol",
                "luvatrix_ui.planes_runtime",
                "luvatrix_ui.planning",
                "luvatrix_ui.table",
                "luvatrix_ui.text.component",
                "luvatrix_ui.text.renderer",
                "luvatrix_ui.ui_ir",
            ),
        )

    def test_lazy_ui_exports_preserve_public_object_identity(self) -> None:
        result = self._run_import_probe(
            """
            from luvatrix_ui import TableColumn
            from luvatrix_ui.table import TableColumn as DirectTableColumn
            from luvatrix_ui.text import TextComponent
            from luvatrix_ui.text.component import TextComponent as DirectTextComponent

            assert TableColumn is DirectTableColumn
            assert TextComponent is DirectTextComponent
            """
        )

        self.assertIn("luvatrix_ui.table.component", result["modules"])
        self.assertIn("luvatrix_ui.text.component", result["modules"])

    def test_lazy_app_runtime_exports_preserve_public_object_identity(self) -> None:
        result = self._run_import_probe(
            """
            from luvatrix.app import AppContext, AppRuntime, InteractionAwareWorkScheduler
            from luvatrix_core.core.app_runtime import AppContext as DirectAppContext
            from luvatrix_core.core.app_runtime import AppRuntime as DirectAppRuntime
            from luvatrix_core.core.interaction_work import (
                InteractionAwareWorkScheduler as DirectInteractionAwareWorkScheduler,
            )

            assert AppContext is DirectAppContext
            assert AppRuntime is DirectAppRuntime
            assert InteractionAwareWorkScheduler is DirectInteractionAwareWorkScheduler
            """
        )

        self.assertIn("luvatrix_core.core.app_runtime", result["modules"])
        self.assertIn("luvatrix_core.core.interaction_work", result["modules"])


if __name__ == "__main__":
    unittest.main()
