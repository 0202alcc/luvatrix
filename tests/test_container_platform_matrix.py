from __future__ import annotations

from pathlib import Path
import sys
import unittest

from luvatrix.app import MissingOptionalDependencyError, validate_app_install

ROOT = Path(__file__).resolve().parents[1]

CONTAINER_EXAMPLES = (
    "examples/container_motion",
    "examples/static_motion",
)

# Targets whose validation must succeed on every CI host (no native SDK,
# no Mac extras needed). macOS GUI targets are handled separately below.
ALWAYS_VALID_TARGETS = (
    "headless",
    "web",
    "ios-simulator",
    "android-emulator",
)

MACOS_ONLY_TARGETS = (
    "macos-metal",
    "macos",
)


class ContainerPlatformMatrixTests(unittest.TestCase):
    """Container apps must validate for every platform they can target.

    The container runtime (`luvatrix_ui.planes_*`) is pure Python, and the
    native bundlers ship `luvatrix_ui` with every app that imports it, so
    container apps are structurally valid on all render targets. This
    pins that matrix in CI.
    """

    def test_container_examples_validate_on_all_portable_targets(self) -> None:
        for example in CONTAINER_EXAMPLES:
            for render in ALWAYS_VALID_TARGETS:
                with self.subTest(example=example, render=render):
                    validation = validate_app_install(ROOT / example, render=render)
                    self.assertTrue(validation.ok, msg=f"{example} invalid for {render}")

    def test_macos_targets_validate_on_mac_and_fail_with_hint_elsewhere(self) -> None:
        for example in CONTAINER_EXAMPLES:
            for render in MACOS_ONLY_TARGETS:
                with self.subTest(example=example, render=render):
                    if sys.platform == "darwin":
                        validation = validate_app_install(ROOT / example, render=render)
                        self.assertTrue(validation.ok, msg=f"{example} invalid for {render}")
                    else:
                        # Documented behavior: macOS extras only fail when the
                        # renderer is selected, with an actionable install hint.
                        with self.assertRaises(MissingOptionalDependencyError) as ctx:
                            validate_app_install(ROOT / example, render=render)
                        message = str(ctx.exception)
                        self.assertIn("pip install", message)
                        self.assertIn("luvatrix[", message)


if __name__ == "__main__":
    unittest.main()
