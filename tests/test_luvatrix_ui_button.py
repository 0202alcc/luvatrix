import unittest

from luvatrix_ui.controls.button import ButtonModel
from luvatrix_ui.controls.interaction import parse_hdi_press_event


def _press_event(phase: str):
    press = parse_hdi_press_event("press", {"phase": phase, "key": "enter", "active_keys": ["enter"]})
    if press is None:
        raise AssertionError("Expected valid press event")
    return press


class ButtonModelTests(unittest.TestCase):
    def test_hover_and_press_flow(self) -> None:
        button = ButtonModel()
        self.assertEqual(button.state, "idle")

        button.set_hovered(True)
        self.assertEqual(button.state, "hover")

        button.on_press(_press_event("down"))
        self.assertEqual(button.state, "press_down")

        button.on_press(_press_event("hold_start"))
        self.assertEqual(button.state, "press_hold")

        button.on_press(_press_event("hold_tick"))
        self.assertEqual(button.state, "press_hold")

        button.on_press(_press_event("up"))
        self.assertEqual(button.state, "hover")

    def test_cancel_returns_to_idle_when_not_hovered(self) -> None:
        button = ButtonModel(hovered=True)
        button.on_press(_press_event("down"))
        self.assertEqual(button.state, "press_down")

        button.set_hovered(False)
        self.assertEqual(button.state, "idle")

        button.on_press(_press_event("cancel"))
        self.assertEqual(button.state, "idle")

    def test_disabled_wins_and_ignores_press_updates(self) -> None:
        button = ButtonModel(hovered=True)
        button.set_disabled(True)
        self.assertEqual(button.state, "disabled")

        button.on_press(_press_event("down"))
        self.assertEqual(button.state, "disabled")

        button.set_disabled(False)
        self.assertEqual(button.state, "hover")

    def test_parse_hdi_press_event_rejects_non_press_and_unknown_phase(self) -> None:
        self.assertIsNone(parse_hdi_press_event("key_down", {"phase": "down"}))
        self.assertIsNone(parse_hdi_press_event("press", {"phase": "unknown"}))


if __name__ == "__main__":
    unittest.main()
