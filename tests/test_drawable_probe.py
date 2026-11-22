"""Drawable alpha probe: pure analysis of a CAMetalDrawable texture readback
plus the unified_runtime backend walk.

SL-38b follow-up: Alec's eyeball at b4dc238 said the cards render SOLID over
the glossy behind-window material. The rasterizer readback is now
alpha-truthful and the Metal pipeline is statically alpha-correct, so the
remaining question is what the PRESENTED drawable actually carries before CA
composites it. The macOS backend blits the drawable texture into a
CPU-readable probe texture on present; this module's analysis is pure numpy
so it is fully testable off the Mac.
"""
from __future__ import annotations

import types
import unittest

import numpy as np

from luvatrix_core.core.drawable_probe import (
    DrawableProbeCapture,
    ProbeRegion,
    analyze_capture,
    default_probe_regions,
)
from luvatrix_core.core.scene_graph import (
    ClearNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
    TextNode,
)


def _frame(nodes) -> SceneFrame:
    return SceneFrame(
        logical_width=200,
        logical_height=100,
        display_width=200,
        display_height=100,
        revision=7,
        ts_ns=1,
        nodes=tuple(nodes),
    )


class TestDefaultProbeRegions(unittest.TestCase):
    def test_translucent_fills_get_regions_with_expected_alpha(self) -> None:
        frame = _frame(
            [
                ClearNode((0, 0, 0, 0)),
                RoundedRectNode(10, 10, 80, 30, 6, (16, 16, 16, 166)),
                RoundedRectNode(10, 50, 80, 30, 6, (16, 16, 16, 191)),
                RectNode(0, 0, 200, 100, (18, 18, 18, 255)),  # opaque: not a probe fill
            ]
        )
        regions = default_probe_regions(frame)
        fills = [r for r in regions if r.expected_alpha is not None]
        self.assertEqual([r.expected_alpha for r in fills], [166, 191])
        # Region must sit strictly inside the fill (no AA edge pixels).
        first = fills[0]
        self.assertGreater(first.x, 10)
        self.assertGreater(first.y, 10)
        self.assertLess(first.x + first.width, 10 + 80)
        self.assertLess(first.y + first.height, 10 + 30)

    def test_text_node_gets_a_region(self) -> None:
        frame = _frame([ClearNode((0, 0, 0, 0)), TextNode("Now Playing", 20, 40)])
        regions = default_probe_regions(frame)
        texts = [r for r in regions if "text" in r.name]
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].x, 20)
        self.assertEqual(texts[0].y, 40)
        self.assertGreater(texts[0].width, 0)
        self.assertGreater(texts[0].height, 0)

    def test_gap_region_between_stacked_fills(self) -> None:
        frame = _frame(
            [
                ClearNode((0, 0, 0, 0)),
                RoundedRectNode(10, 10, 80, 30, 6, (16, 16, 16, 166)),
                RoundedRectNode(10, 50, 80, 30, 6, (16, 16, 16, 166)),
            ]
        )
        regions = default_probe_regions(frame)
        gaps = [r for r in regions if "gap" in r.name]
        self.assertEqual(len(gaps), 1)
        gap = gaps[0]
        # The gap spans the space between the two stacked fills.
        self.assertGreaterEqual(gap.y, 40)
        self.assertLessEqual(gap.y + gap.height, 50)
        self.assertGreater(gap.height, 0)

    def test_gap_falls_back_to_a_corner_sample(self) -> None:
        frame = _frame([ClearNode((0, 0, 0, 0))])
        regions = default_probe_regions(frame)
        gaps = [r for r in regions if "gap" in r.name]
        self.assertEqual(len(gaps), 1)


class TestAnalyzeCapture(unittest.TestCase):
    def _buffer(self, w: int = 16, h: int = 8) -> np.ndarray:
        buf = np.zeros((h, w, 4), dtype=np.uint8)
        buf[:, :] = (0, 0, 0, 255)  # opaque BGRA
        return buf

    def test_global_alpha_stats(self) -> None:
        buf = self._buffer()
        buf[0, 0] = (0, 0, 0, 0)  # one transparent gap pixel
        buf[1, 1:4] = (16, 16, 16, 166)  # three fill pixels
        report = analyze_capture(
            buf.tobytes(),
            16,
            8,
            viewport=(0.0, 0.0, 16.0, 8.0),
            logical_size=(16, 8),
            regions=[],
        )
        stats = report["alpha"]
        self.assertEqual(stats["transparent_px"], 1)
        self.assertEqual(stats["mid_alpha_px"], 3)
        self.assertEqual(stats["opaque_px"], 16 * 8 - 4)
        self.assertEqual(stats["min"], 0)
        self.assertEqual(stats["max"], 255)

    def test_region_maps_through_letterboxed_viewport(self) -> None:
        # 2x scale, letterboxed: viewport (4, 0, 16, 8) for a 8x4 logical scene.
        buf = np.zeros((8, 24, 4), dtype=np.uint8)
        buf[:, :] = (0, 0, 0, 255)
        # Logical fill (1,1)-(3,2) -> pixel (4+2, 0+2) .. (4+6, 0+4).
        buf[2:4, 6:10] = (16, 16, 16, 166)
        report = analyze_capture(
            buf.tobytes(),
            24,
            8,
            viewport=(4.0, 0.0, 16.0, 8.0),
            logical_size=(8, 4),
            regions=[ProbeRegion("fill[0]_a166", 1.0, 1.0, 2.0, 1.0, expected_alpha=166)],
        )
        region = report["regions"][0]
        self.assertEqual(region["n_px"], 8)
        self.assertAlmostEqual(region["alpha_mean"], 166.0, places=1)
        self.assertEqual(region["expected_alpha"], 166)
        self.assertTrue(region["alpha_matches_expected"])

    def test_region_alpha_mismatch_is_flagged_not_raised(self) -> None:
        buf = self._buffer()
        report = analyze_capture(
            buf.tobytes(),
            16,
            8,
            viewport=(0.0, 0.0, 16.0, 8.0),
            logical_size=(16, 8),
            regions=[ProbeRegion("fill[0]_a166", 2.0, 2.0, 4.0, 4.0, expected_alpha=166)],
        )
        region = report["regions"][0]
        self.assertEqual(region["expected_alpha"], 166)
        self.assertAlmostEqual(region["alpha_mean"], 255.0, places=1)
        self.assertFalse(region["alpha_matches_expected"])

    def test_region_is_clipped_to_the_drawable(self) -> None:
        buf = self._buffer()
        report = analyze_capture(
            buf.tobytes(),
            16,
            8,
            viewport=(0.0, 0.0, 16.0, 8.0),
            logical_size=(16, 8),
            regions=[ProbeRegion("edge", 14.0, 6.0, 8.0, 8.0)],
        )
        self.assertEqual(report["regions"][0]["n_px"], 2 * 2)

    def test_bgra_channel_order_in_rgb_mean(self) -> None:
        buf = self._buffer()
        buf[3:5, 3:5] = (30, 20, 10, 166)  # B=30, G=20, R=10
        report = analyze_capture(
            buf.tobytes(),
            16,
            8,
            viewport=(0.0, 0.0, 16.0, 8.0),
            logical_size=(16, 8),
            regions=[ProbeRegion("fill", 3.0, 3.0, 2.0, 2.0)],
        )
        rgb = report["regions"][0]["rgb_mean"]
        self.assertAlmostEqual(rgb[0], 10.0, places=1)
        self.assertAlmostEqual(rgb[1], 20.0, places=1)
        self.assertAlmostEqual(rgb[2], 30.0, places=1)

    def test_report_carries_capture_metadata(self) -> None:
        buf = self._buffer()
        capture = DrawableProbeCapture(
            pixels=buf.tobytes(), width=16, height=8, revision=42, regions=[]
        )
        report = analyze_capture(
            capture.pixels,
            capture.width,
            capture.height,
            viewport=(0.0, 0.0, 16.0, 8.0),
            logical_size=(16, 8),
            regions=capture.regions,
            revision=capture.revision,
        )
        self.assertEqual(report["revision"], 42)
        self.assertEqual(report["width"], 16)
        self.assertEqual(report["height"], 8)


class TestUnifiedRuntimeWalk(unittest.TestCase):
    """The MCP provider must reach the macOS Metal scene backend through the
    scene display runtime — and report cleanly when the target is not the
    probe-capable Metal backend (headless/web/cpu runs)."""

    def _runtime(self, target) -> object:
        from luvatrix_core.core.unified_runtime import UnifiedRuntime

        runtime = object.__new__(UnifiedRuntime)
        runtime._scene_display_runtime = types.SimpleNamespace(target=target)
        return runtime

    def test_routes_to_backend_probe_with_arguments(self) -> None:
        calls: list[dict] = []

        class _Backend:
            def request_drawable_probe(self, *, regions=None, timeout_s=2.0):
                calls.append({"regions": regions, "timeout_s": timeout_s})
                return {"available": True, "alpha": {"mid_alpha_px": 3}}

        target = types.SimpleNamespace(backend=_Backend())
        runtime = self._runtime(target)
        payload = runtime._mcp_drawable_probe(
            {"regions": [{"name": "card", "x": 1, "y": 2, "width": 3, "height": 4}], "wait_s": 1.5}
        )
        self.assertTrue(payload["available"])
        self.assertEqual(
            calls,
            [
                {
                    "regions": [{"name": "card", "x": 1, "y": 2, "width": 3, "height": 4}],
                    "timeout_s": 1.5,
                }
            ],
        )

    def test_unavailable_without_scene_runtime(self) -> None:
        from luvatrix_core.core.unified_runtime import UnifiedRuntime

        runtime = object.__new__(UnifiedRuntime)
        runtime._scene_display_runtime = None
        payload = runtime._mcp_drawable_probe({})
        self.assertFalse(payload["available"])
        self.assertIn("reason", payload)

    def test_unavailable_when_backend_lacks_the_probe(self) -> None:
        target = types.SimpleNamespace(backend=object())
        payload = self._runtime(target)._mcp_drawable_probe({})
        self.assertFalse(payload["available"])
        self.assertIn("reason", payload)

    def test_wires_present_hook_to_lifecycle_invalidate(self) -> None:
        """The idle-arm fix's runtime half: the backend's present-request hook
        becomes the app's invalidate(), so an armed probe on an idle
        invalidation-driven app still gets a frame inside the wait window."""
        wired: list = []
        backend = types.SimpleNamespace(
            set_drawable_probe_present_hook=lambda hook: wired.append(hook))
        runtime = self._runtime(types.SimpleNamespace(backend=backend))
        lifecycle = types.SimpleNamespace(invalidate=lambda: "invalidated")
        runtime._wire_drawable_probe_present_hook(lifecycle)
        self.assertEqual(len(wired), 1)
        self.assertEqual(wired[0](), "invalidated")

    def test_wire_skips_when_backend_or_invalidate_missing(self) -> None:
        runtime = self._runtime(types.SimpleNamespace(backend=object()))
        runtime._wire_drawable_probe_present_hook(types.SimpleNamespace())
        self._runtime(None)._wire_drawable_probe_present_hook(
            types.SimpleNamespace(invalidate=lambda: None))


if __name__ == "__main__":
    unittest.main()
