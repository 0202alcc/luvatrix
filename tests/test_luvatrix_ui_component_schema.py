from __future__ import annotations

import unittest

from luvatrix_ui.component_schema import BoundingBox, CoordinatePoint, DisplayableArea, parse_coordinate_notation
from luvatrix_ui.controls.interaction import parse_hdi_press_event
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import TextLayoutMetrics, TextMeasureRequest, TextRenderBatch, TextRenderer


class _FakeTextRenderer(TextRenderer):
    def __init__(self) -> None:
        self.last_measure: TextMeasureRequest | None = None
        self.last_batch: TextRenderBatch | None = None

    def measure_text(self, request: TextMeasureRequest) -> TextLayoutMetrics:
        self.last_measure = request
        width = float(len(request.text)) * request.font_size_px * 0.5
        return TextLayoutMetrics(width_px=width, height_px=request.font_size_px, baseline_px=request.font_size_px * 0.8)

    def draw_text_batch(self, batch: TextRenderBatch) -> None:
        self.last_batch = batch


class ComponentSchemaTests(unittest.TestCase):
    def test_parse_coordinate_notation_with_and_without_frame(self) -> None:
        p1 = parse_coordinate_notation("10,20", default_frame="screen_tl")
        self.assertEqual((p1.x, p1.y, p1.frame), (10.0, 20.0, "screen_tl"))

        p2 = parse_coordinate_notation("cartesian_bl: 1.5, 2.5")
        self.assertEqual((p2.x, p2.y, p2.frame), (1.5, 2.5, "cartesian_bl"))

    def test_text_component_defaults_visual_bounds_and_allows_interaction_override(self) -> None:
        renderer = _FakeTextRenderer()
        display = DisplayableArea(content_width_px=100, content_height_px=50)
        component = TextComponent(component_id="title", text="Luvatrix", position=CoordinatePoint(4.0, 8.0))

        _, visual = component.layout(renderer, display)
        self.assertEqual(component.interaction_bounds(), visual)

        component.interaction_bounds_override = BoundingBox(x=0.0, y=0.0, width=10.0, height=10.0)
        self.assertEqual(component.interaction_bounds().width, 10.0)
        self.assertEqual(component.visual_bounds().width, visual.width)

    def test_component_can_detect_press_events(self) -> None:
        component = TextComponent(component_id="title", text="L")
        component.set_hovered(True)
        press = parse_hdi_press_event("press", {"phase": "down", "key": "enter", "active_keys": ["enter"]})
        assert press is not None
        consumed = component.on_press(press)
        self.assertTrue(consumed)
        self.assertEqual(component.press_state, "press_down")


if __name__ == "__main__":
    unittest.main()
