from __future__ import annotations

import unittest

from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.controls.svg_renderer import SVGRenderBatch, SVGRenderer


class _CaptureSVGRenderer(SVGRenderer):
    def __init__(self) -> None:
        self.batches: list[SVGRenderBatch] = []

    def draw_svg_batch(self, batch: SVGRenderBatch) -> None:
        self.batches.append(batch)


class SVGRendererContractTests(unittest.TestCase):
    def test_svg_component_layout_preserves_explicit_target_size(self) -> None:
        component = SVGComponent(
            component_id="icon",
            svg_markup='<svg width="8" height="8"><circle cx="4" cy="4" r="4" fill="#00ff00"/></svg>',
            position=CoordinatePoint(10.0, 12.0, "screen_tl"),
            width=96.0,
            height=24.0,
            opacity=0.8,
        )
        command, bounds = component.layout()
        self.assertEqual((command.width, command.height), (96.0, 24.0))
        self.assertEqual((bounds.width, bounds.height), (96.0, 24.0))
        self.assertEqual(command.frame, "screen_tl")

    def test_svg_component_renders_as_batch(self) -> None:
        renderer = _CaptureSVGRenderer()
        component = SVGComponent(
            component_id="logo",
            svg_markup='<svg width="4" height="4"><rect x="0" y="0" width="4" height="4" fill="#123456"/></svg>',
            width=40.0,
            height=40.0,
        )
        batch = component.render(renderer)
        self.assertEqual(len(renderer.batches), 1)
        self.assertEqual(len(batch.commands), 1)
        self.assertEqual(batch.commands[0].component_id, "logo")


if __name__ == "__main__":
    unittest.main()
