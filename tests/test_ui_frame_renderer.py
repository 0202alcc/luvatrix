from __future__ import annotations

import unittest

import torch
from matplotlib import font_manager

from luvatrix_core.core.app_runtime import AppContext
from luvatrix_core.core.sensor_manager import SensorSample
from luvatrix_core.core.ui_frame_renderer import MatrixUIFrameRenderer
from luvatrix_core.core.window_matrix import WindowMatrix
from luvatrix_ui.component_schema import CoordinatePoint
from luvatrix_ui.controls.svg_component import SVGComponent
from luvatrix_ui.text.component import TextComponent
from luvatrix_ui.text.renderer import FontSpec, TextAppearance, TextSizeSpec


class _NoopHDI:
    def poll_events(self, max_events: int):
        _ = max_events
        return []


class _NoopSensor:
    def read_sensor(self, sensor_type: str) -> SensorSample:
        return SensorSample(
            sample_id=1,
            ts_ns=1,
            sensor_type=sensor_type,
            status="UNAVAILABLE",
            value=None,
            unit=None,
        )


class MatrixUIFrameRendererTests(unittest.TestCase):
    def test_svg_renders_to_explicit_target_size(self) -> None:
        renderer = MatrixUIFrameRenderer()
        from luvatrix_ui.component_schema import DisplayableArea

        renderer.begin_frame(DisplayableArea(content_width_px=40, content_height_px=30), clear_color=(0, 0, 0, 255))
        svg = SVGComponent(
            component_id="rect",
            svg_markup='<svg width="10" height="5" viewBox="0 0 10 5"><rect x="0" y="0" width="10" height="5" fill="#ff0000"/></svg>',
            position=CoordinatePoint(3.0, 4.0, "screen_tl"),
            width=20.0,
            height=10.0,
        )
        batch = svg.render(renderer)
        self.assertEqual(len(batch.commands), 1)
        frame = renderer.end_frame()

        self.assertEqual(tuple(frame.shape), (30, 40, 4))
        self.assertTrue(torch.equal(frame[6, 5, :3], torch.tensor([255, 0, 0], dtype=torch.uint8)))
        self.assertTrue(torch.equal(frame[0, 0, :3], torch.tensor([0, 0, 0], dtype=torch.uint8)))
        self.assertTrue(torch.equal(frame[13, 23, :3], torch.tensor([0, 0, 0], dtype=torch.uint8)))

    def test_app_context_finalizes_svg_components_to_matrix(self) -> None:
        matrix = WindowMatrix(20, 20)
        ctx = AppContext(
            matrix=matrix,
            hdi=_NoopHDI(),  # type: ignore[arg-type]
            sensor_manager=_NoopSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        renderer = MatrixUIFrameRenderer()
        svg = SVGComponent(
            component_id="dot",
            svg_markup='<svg width="4" height="4" viewBox="0 0 4 4"><rect x="0" y="0" width="4" height="4" fill="#00ff00"/></svg>',
            position=CoordinatePoint(2.0, 3.0, "screen_tl"),
            width=6.0,
            height=6.0,
        )

        ctx.begin_ui_frame(renderer)
        ctx.mount_component(svg)
        event = ctx.finalize_ui_frame()

        self.assertEqual(event.revision, 1)
        snap = ctx.read_matrix_snapshot()
        self.assertTrue(torch.equal(snap[4, 4, :3], torch.tensor([0, 255, 0], dtype=torch.uint8)))

    def test_text_measure_and_draw_batch(self) -> None:
        renderer = MatrixUIFrameRenderer()
        from luvatrix_ui.component_schema import DisplayableArea
        from luvatrix_ui.text.renderer import TextMeasureRequest

        renderer.begin_frame(DisplayableArea(content_width_px=80, content_height_px=50), clear_color=(0, 0, 0, 255))
        text = TextComponent(
            component_id="txt",
            text="hello",
            position=CoordinatePoint(4.0, 6.0, "screen_tl"),
            appearance=TextAppearance(color_hex="#ffffff"),
            size=TextSizeSpec(unit="px", value=14.0),
        )
        metrics = renderer.measure_text(
            TextMeasureRequest(
                text="hello",
                font=FontSpec(),
                font_size_px=14.0,
                appearance=TextAppearance(color_hex="#ffffff"),
            )
        )
        self.assertGreater(metrics.width_px, 0.0)
        batch = text.render(renderer, DisplayableArea(content_width_px=80, content_height_px=50))
        self.assertEqual(len(batch.commands), 1)
        frame = renderer.end_frame()
        self.assertGreater(int(frame[:, :, :3].sum().item()), 0)

    def test_text_file_font_support(self) -> None:
        renderer = MatrixUIFrameRenderer()
        from luvatrix_ui.component_schema import DisplayableArea
        from luvatrix_ui.text.renderer import TextMeasureRequest

        font_path = font_manager.findfont("DejaVu Sans")
        renderer.begin_frame(DisplayableArea(content_width_px=60, content_height_px=40), clear_color=(0, 0, 0, 255))
        metrics = renderer.measure_text(
            TextMeasureRequest(
                text="abc",
                font=FontSpec(family="", file_path=font_path),
                font_size_px=12.0,
                appearance=TextAppearance(color_hex="#ffffff"),
            )
        )
        self.assertGreater(metrics.width_px, 0.0)
        frame = renderer.end_frame()
        self.assertEqual(tuple(frame.shape), (40, 60, 4))

    def test_app_context_finalizes_mixed_text_and_svg_components(self) -> None:
        matrix = WindowMatrix(24, 24)
        ctx = AppContext(
            matrix=matrix,
            hdi=_NoopHDI(),  # type: ignore[arg-type]
            sensor_manager=_NoopSensor(),  # type: ignore[arg-type]
            granted_capabilities={"window.write"},
        )
        renderer = MatrixUIFrameRenderer()
        svg = SVGComponent(
            component_id="shape",
            svg_markup='<svg width="4" height="4"><rect x="0" y="0" width="4" height="4" fill="#0000ff"/></svg>',
            position=CoordinatePoint(10.0, 10.0, "screen_tl"),
            width=8.0,
            height=8.0,
        )
        text = TextComponent(
            component_id="label",
            text="x",
            position=CoordinatePoint(1.0, 1.0, "screen_tl"),
            appearance=TextAppearance(color_hex="#ffffff"),
            size=TextSizeSpec(unit="px", value=12.0),
        )
        ctx.begin_ui_frame(renderer)
        ctx.mount_component(svg)
        ctx.mount_component(text)
        ctx.finalize_ui_frame()
        snap = ctx.read_matrix_snapshot()
        self.assertGreater(int(snap[:, :, :3].sum().item()), 0)


if __name__ == "__main__":
    unittest.main()
