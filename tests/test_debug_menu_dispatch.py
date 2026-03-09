from __future__ import annotations

import unittest

from luvatrix_core.core.debug_menu import DebugMenuDispatcher


class DebugMenuDispatchTests(unittest.TestCase):
    def test_unknown_action_degrades_to_noop_warning(self) -> None:
        warnings: list[str] = []
        dispatcher = DebugMenuDispatcher(warning_sink=warnings.append)
        result = dispatcher.dispatch("debug.unknown")
        self.assertEqual(result.status, "UNSUPPORTED")
        self.assertEqual(result.warning, "unknown action: debug.unknown")
        self.assertEqual(warnings, ["unknown action: debug.unknown"])

    def test_disabled_action_degrades_without_handler_run(self) -> None:
        warnings: list[str] = []
        called: list[str] = []
        dispatcher = DebugMenuDispatcher(warning_sink=warnings.append)
        dispatcher.register(
            "debug.capture.start",
            lambda _ctx: called.append("ran"),
            is_enabled=lambda _ctx: False,
        )
        result = dispatcher.dispatch("debug.capture.start")
        self.assertEqual(result.status, "DISABLED")
        self.assertEqual(called, [])
        self.assertEqual(warnings, ["disabled action: debug.capture.start"])

    def test_handler_failure_is_caught_and_reported(self) -> None:
        warnings: list[str] = []
        dispatcher = DebugMenuDispatcher(warning_sink=warnings.append)
        dispatcher.register("debug.capture.start", lambda _ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        result = dispatcher.dispatch("debug.capture.start")
        self.assertEqual(result.status, "ERROR")
        self.assertEqual(result.warning, "handler failure for debug.capture.start: RuntimeError")
        self.assertEqual(warnings, ["handler failure for debug.capture.start: RuntimeError"])

    def test_successful_action_executes(self) -> None:
        called: list[dict[str, object]] = []
        dispatcher = DebugMenuDispatcher()
        dispatcher.register("debug.capture.start", lambda ctx: called.append(ctx))
        result = dispatcher.dispatch("debug.capture.start", {"seed": 1337})
        self.assertEqual(result.status, "EXECUTED")
        self.assertEqual(called, [{"seed": 1337}])


if __name__ == "__main__":
    unittest.main()
