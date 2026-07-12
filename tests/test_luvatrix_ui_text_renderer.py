from __future__ import annotations

import unittest

from luvatrix_ui.component_schema import CoordinatePoint, DisplayableArea
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import FontSpec, TextLayoutMetrics, TextMeasureRequest, TextRenderBatch, TextRenderer, TextSizeSpec
from luvatrix_ui.text.wrapping import TextWrapping


class _CaptureTextRenderer(TextRenderer):
    def __init__(self) -> None:
        self.measure_calls: list[TextMeasureRequest] = []
        self.draw_batches: list[TextRenderBatch] = []

    def measure_text(self, request: TextMeasureRequest) -> TextLayoutMetrics:
        self.measure_calls.append(request)
        return TextLayoutMetrics(
            width_px=float(len(request.text)) * request.font_size_px * 0.5,
            height_px=request.font_size_px,
            baseline_px=request.font_size_px * 0.75,
        )

    def draw_text_batch(self, batch: TextRenderBatch) -> None:
        self.draw_batches.append(batch)


class TextRendererContractTests(unittest.TestCase):
    def test_default_font_is_comicmono(self) -> None:
        font = FontSpec()
        self.assertEqual(font.family, "Comic Mono")
        self.assertEqual(font.source_kind, "system")

    def test_font_size_can_be_ratio_of_displayable_dimensions(self) -> None:
        display = DisplayableArea(content_width_px=800, content_height_px=600)
        self.assertEqual(TextSizeSpec(unit="ratio_display_height", value=0.1).resolve_px(display), 60.0)
        self.assertEqual(TextSizeSpec(unit="ratio_display_width", value=0.1).resolve_px(display), 80.0)

    def test_text_component_renders_as_single_batch_command(self) -> None:
        renderer = _CaptureTextRenderer()
        display = DisplayableArea(content_width_px=300, content_height_px=200)
        component = TextComponent(
            component_id="headline",
            text="render all at once",
            position=CoordinatePoint(12.0, 20.0, "screen_tl"),
            size=TextSizeSpec(unit="ratio_display_height", value=0.05),
        )

        batch = component.render(renderer, display)

        self.assertEqual(len(renderer.draw_batches), 1)
        self.assertEqual(len(batch.commands), 1)
        self.assertEqual(batch.commands[0].text, "render all at once")
        self.assertEqual(renderer.measure_calls[0].font_size_px, 10.0)
        self.assertEqual(batch.commands[0].frame, "screen_tl")

    def test_text_component_wraps_into_one_scene_command_per_line(self) -> None:
        renderer = _CaptureTextRenderer()
        display = DisplayableArea(content_width_px=300, content_height_px=200)
        component = TextComponent(
            component_id="body",
            text="hello world",
            position=CoordinatePoint(12.0, 20.0, "screen_tl"),
            size=TextSizeSpec(value=10.0),
            max_width_px=30.0,
            wrapping=TextWrapping(),
        )

        batch = component.render(renderer, display)

        self.assertEqual([command.text for command in batch.commands], ["hello", "world"])
        self.assertEqual([command.y for command in batch.commands], [20.0, 32.0])
        self.assertEqual(component.visual_bounds().height, 24.0)


if __name__ == "__main__":
    unittest.main()
