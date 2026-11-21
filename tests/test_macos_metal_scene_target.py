from __future__ import annotations

import types
import unittest
import unittest.mock
import contextlib
import ctypes
import io

from luvatrix_core.core.scene_graph import CircleNode, ClearNode, CpuLayerNode, ImageNode, RectNode, RoundedRectNode, SceneFrame, ShaderRectNode, TextNode
from luvatrix_core.core.scene_rasterizer import rasterize_scene_frame
from luvatrix_core.platform.macos import metal_scene_target as mst
from luvatrix_core.platform.macos.metal_scene_target import (
    _MacOSMetalSceneState,
    _ReusableMetalBuffer,
    _clear_color,
    _collect_circle_instances,
    _collect_rect_instances,
    _collect_rounded_rect_instances,
    _needs_z_ordered_batches,
    _plan_z_ordered_batches,
    _scene_view_uniform,
    _write_reusable_float_buffer,
)


class _FakeContents:
    def __init__(self, storage: bytearray) -> None:
        self.storage = storage

    def as_buffer(self, length: int) -> memoryview:
        return memoryview(self.storage)[:length]


class _FakeBuffer:
    def __init__(self, capacity: int) -> None:
        self.storage = bytearray(capacity)

    def contents(self) -> _FakeContents:
        return _FakeContents(self.storage)


class _FakeDevice:
    def __init__(self) -> None:
        self.allocations: list[int] = []

    def newBufferWithLength_options_(self, capacity: int, _options: int) -> _FakeBuffer:
        self.allocations.append(capacity)
        return _FakeBuffer(capacity)


class MacOSMetalSceneTargetTests(unittest.TestCase):
    def test_scene_view_uniform_carries_content_translation(self) -> None:
        frame = SceneFrame(1, 200, 100, 200, 100, 1, (), content_offset_x=3.5, content_offset_y=17.25)

        self.assertEqual(list(_scene_view_uniform(frame)), [200.0, 100.0, 3.5, 17.25])

    def test_reusable_float_buffer_grows_by_capacity_and_reuses_allocation(self) -> None:
        device = _FakeDevice()
        slot = _ReusableMetalBuffer()
        small = (ctypes.c_float * 8)(*range(8))
        large = (ctypes.c_float * 2048)(*range(2048))

        first = _write_reusable_float_buffer(device, slot, small)
        second = _write_reusable_float_buffer(device, slot, small)
        grown = _write_reusable_float_buffer(device, slot, large)

        self.assertIs(first, second)
        self.assertIsNot(grown, first)
        self.assertEqual(len(device.allocations), 2)
        self.assertGreaterEqual(slot.capacity_bytes, ctypes.sizeof(large))
        self.assertEqual(bytes(grown.storage[: ctypes.sizeof(large)]), bytes(large))

    def test_collect_rect_instances_batches_rect_like_nodes(self) -> None:
        frame = SceneFrame(
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            revision=1,
            ts_ns=1,
            nodes=(
                ClearNode((1, 2, 3, 255)),
                RectNode(1, 2, 3, 4, (10, 20, 30, 255)),
                # radius > 0 leaves the plain-rect batch (rounded pipeline)
                RoundedRectNode(5, 6, 7, 8, 2, (40, 50, 60, 128)),
                # radius == 0 stays on the cheap plain-rect path
                RoundedRectNode(13, 14, 15, 16, 0, (50, 60, 70, 128)),
                ShaderRectNode(9, 10, 11, 12, shader="solid", color_rgba=(70, 80, 90, 64)),
                CircleNode(20, 30, 5, (100, 110, 120, 255)),
                TextNode("not batched", 1, 1),
            ),
        )

        rects = _collect_rect_instances(frame)

        self.assertEqual(len(rects), 3)
        self.assertEqual(rects[0][:4], (1.0, 2.0, 3.0, 4.0))
        self.assertEqual(rects[1][:4], (13.0, 14.0, 15.0, 16.0))
        self.assertEqual(rects[2][:4], (9.0, 10.0, 11.0, 12.0))

    def test_collect_rounded_rect_instances_honors_radius(self) -> None:
        """Mac round-3 evidence: RoundedRectNode.radius was dropped entirely,
        so the login wall's glass-tint underlay rasterized square behind the
        (correctly rounded) native glass. The rounded pipeline must receive
        the radius in points alongside the fill."""
        frame = SceneFrame(
            logical_width=1280,
            logical_height=800,
            display_width=1280,
            display_height=800,
            revision=1,
            ts_ns=1,
            nodes=(
                RoundedRectNode(450, 420, 380, 40, 20, (255, 255, 255, 24)),
                RectNode(0, 0, 1280, 800, (18, 18, 18, 255)),
                CircleNode(20, 30, 5, (100, 110, 120, 255)),
            ),
        )

        rounded = _collect_rounded_rect_instances(frame)

        self.assertEqual(len(rounded), 1)
        inst = rounded[0]
        self.assertEqual(len(inst), 16)  # same packing as circle instances
        self.assertEqual(inst[:4], (450.0, 420.0, 380.0, 40.0))
        self.assertEqual(inst[4:8], (1.0, 1.0, 1.0, 24 / 255.0))
        self.assertEqual(inst[8:12], (0.0, 0.0, 0.0, 0.0))  # no stroke
        self.assertEqual(inst[12], 20.0)  # corner radius in points

    def test_collect_rounded_rect_instances_clamps_radius(self) -> None:
        frame = SceneFrame(
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            revision=1,
            ts_ns=1,
            nodes=(RoundedRectNode(0, 0, 90, 36, 50, (1, 2, 3, 255)),),
        )

        rounded = _collect_rounded_rect_instances(frame)

        self.assertEqual(rounded[0][12], 18.0)  # min(w, h) / 2

    def test_collect_rounded_rect_instances_skips_zero_radius(self) -> None:
        frame = SceneFrame(
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            revision=1,
            ts_ns=1,
            nodes=(RoundedRectNode(1, 2, 3, 4, 0, (10, 20, 30, 255)),),
        )

        self.assertEqual(_collect_rounded_rect_instances(frame), [])

    def test_collect_circle_instances_batches_circles_separately(self) -> None:
        frame = SceneFrame(
            logical_width=100,
            logical_height=80,
            display_width=100,
            display_height=80,
            revision=1,
            ts_ns=1,
            nodes=(
                CircleNode(20, 30, 5, (100, 110, 120, 255), stroke_rgba=(10, 20, 30, 128), stroke_width=2),
                RectNode(1, 2, 3, 4, (10, 20, 30, 255)),
            ),
        )

        circles = _collect_circle_instances(frame)

        self.assertEqual(len(circles), 1)
        self.assertEqual(circles[0][:4], (15.0, 25.0, 10.0, 10.0))
        self.assertEqual(circles[0][4:8], (100 / 255.0, 110 / 255.0, 120 / 255.0, 1.0))
        self.assertEqual(circles[0][8:12], (10 / 255.0, 20 / 255.0, 30 / 255.0, 128 / 255.0))
        self.assertEqual(circles[0][12], 0.4)

    def test_clear_color_uses_scene_clear_node(self) -> None:
        frame = SceneFrame(10, 10, 10, 10, 1, 1, nodes=(ClearNode((4, 5, 6, 7)),))

        self.assertEqual(_clear_color(frame, (0, 0, 0, 255)), (4, 5, 6, 7))


class RetinaScaleTests(unittest.TestCase):
    """Live Mac bug (Alec on `9f8b157`): "everything looks pixelated". The
    window is sized in POINTS (1280x800), so the submitted frame's display ==
    logical dims and `_frame_scale` is 1.0 — text textures rasterized at 1x
    while the Retina drawable is 2560x1600 → 2x GPU upscale → chunky text.
    Text must raster at the DRAWABLE scale, same as the viewport."""

    def _points_frame(self, presentation_mode=None) -> SceneFrame:
        return SceneFrame(
            logical_width=1280,
            logical_height=800,
            display_width=1280,   # points, not device pixels — the trap
            display_height=800,
            revision=1,
            ts_ns=1,
            nodes=(),
            presentation_mode=presentation_mode,
        )

    def test_frame_scale_is_1_for_points_frames(self) -> None:
        # Characterization of the bug: display==logical yields 1.0 even on a
        # 2x Retina drawable — this is why text rastered at 1x.
        self.assertEqual(mst._frame_scale(self._points_frame()), 1.0)

    def test_text_raster_scale_follows_drawable(self) -> None:
        frame = self._points_frame()
        self.assertEqual(mst._text_raster_scale(frame, 2560.0, 1600.0), 2.0)
        self.assertEqual(mst._text_raster_scale(frame, 1280.0, 800.0), 1.0)

    def test_text_raster_scale_matches_viewport_policy(self) -> None:
        # Default presentation: min() like _viewport; crop_fit: max().
        frame = self._points_frame()
        self.assertEqual(mst._text_raster_scale(frame, 2560.0, 800.0), 1.0)
        crop = self._points_frame(presentation_mode="crop_fit")
        self.assertEqual(mst._text_raster_scale(crop, 2560.0, 800.0), 2.0)


class _FakeScaleWindow:
    def __init__(self, scale: float) -> None:
        self.scale = scale

    def backingScaleFactor(self) -> float:
        return self.scale


class _FakeScaleLayer:
    def __init__(self) -> None:
        self.contents_scale: float | None = None
        self.drawable_size = None

    def setContentsScale_(self, scale) -> None:
        self.contents_scale = scale

    def setDrawableSize_(self, size) -> None:
        self.drawable_size = size


class LayerScaleLogTests(unittest.TestCase):
    """The Mac pass needs a stderr line proving what scale took — silent
    1x is exactly the failure mode we're killing."""

    def test_resize_applies_backing_scale_and_logs_once_per_change(self) -> None:
        from luvatrix_core.platform.macos.window_system import MacOSWindowHandle

        layer = _FakeScaleLayer()
        window = _FakeScaleWindow(2.0)
        handle = MacOSWindowHandle(window=window, layer=layer)
        log_state: dict = {}

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            mst._resize_layer_for_window(layer, handle, 1280, 800, _log_state=log_state)
            mst._resize_layer_for_window(layer, handle, 1280, 800, _log_state=log_state)

        self.assertEqual(layer.contents_scale, 2.0)
        self.assertEqual((layer.drawable_size[0], layer.drawable_size[1]), (2560.0, 1600.0))
        self.assertIn("contentsScale=2.0", buf.getvalue())
        self.assertIn("drawable=2560x1600", buf.getvalue())
        self.assertEqual(buf.getvalue().count("contentsScale="), 1,
                         "called every present — must log only on change")

        window.scale = 1.0  # dragged to a 1x external display
        buf2 = io.StringIO()
        with contextlib.redirect_stderr(buf2):
            mst._resize_layer_for_window(layer, handle, 1280, 800, _log_state=log_state)
        self.assertIn("contentsScale=1.0", buf2.getvalue())


class _FakeTexture:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.uploads: list[bytes] = []

    def replaceRegion_mipmapLevel_withBytes_bytesPerRow_(self, _region, _level, payload, _bpr) -> None:
        self.uploads.append(bytes(payload))


def _bare_state() -> _MacOSMetalSceneState:
    return _MacOSMetalSceneState(
        device=object(),
        command_queue=None,
        rect_pipeline_state=None,
        circle_pipeline_state=None,
        rounded_rect_pipeline_state=None,
        textured_pipeline_state=None,
        atlas_pipeline_state=None,
        sampler_state=None,
        window_handle=None,
        window_system=None,
    )


class DynamicLayerTextureCacheTests(unittest.TestCase):
    """Live Mac bug (round-6c screenshot): every track card rendered the SAME
    photo. Root cause — one shared `state.dynamic_texture` re-uploaded per
    CpuLayerNode; Metal samples at execution time, so every quad drew the
    LAST upload of the frame. Textures must be keyed by content."""

    def _layer(self, rgba, x: float = 0.0):
        from luvatrix_core.core.scene_graph import CpuLayerNode

        return CpuLayerNode(x, 0.0, float(rgba.shape[1]), float(rgba.shape[0]), rgba, 2)

    def _rgba(self, rgb, size: int = 8):
        np = __import__("numpy")
        return np.full((size, size, 4), (*rgb, 255), dtype=np.uint8)

    def _patched_create(self, made: list):
        def fake_create(_device, w, h):
            tex = _FakeTexture(w, h)
            made.append(tex)
            return tex

        return unittest.mock.patch.object(mst, "_create_texture", side_effect=fake_create)

    def test_distinct_content_gets_distinct_textures(self) -> None:
        state = _bare_state()
        made: list = []
        with self._patched_create(made):
            red = mst._cached_dynamic_layer_texture(state, self._layer(self._rgba((200, 0, 0))))
            blue = mst._cached_dynamic_layer_texture(state, self._layer(self._rgba((0, 0, 200)), x=40.0))
        self.assertIsNot(red, blue, "two art images must not share one texture")
        self.assertEqual(len(made), 2)

    def test_repeat_content_reuses_texture_without_reupload(self) -> None:
        state = _bare_state()
        made: list = []
        art = self._rgba((0, 200, 0))
        with self._patched_create(made):
            first = mst._cached_dynamic_layer_texture(state, self._layer(art))
            second = mst._cached_dynamic_layer_texture(state, self._layer(art, x=40.0))
        self.assertIs(first, second)
        self.assertEqual(len(first.uploads), 1, "cache hit must not re-upload pixels")
        self.assertEqual(len(made), 1)

    def test_cache_is_bounded_lru(self) -> None:
        state = _bare_state()
        made: list = []
        limit = mst._DYNAMIC_LAYER_TEXTURE_LIMIT
        with self._patched_create(made):
            for i in range(limit + 8):
                mst._cached_dynamic_layer_texture(state, self._layer(self._rgba((i % 250, 0, 0))))
            self.assertLessEqual(len(state.dynamic_layer_textures), limit)
            evicted = mst._cached_dynamic_layer_texture(state, self._layer(self._rgba((0, 0, 0))))
        # The oldest entry was evicted, so image 0 creates a fresh texture.
        self.assertIn(evicted, made[1:])


class MacOSMetalZOrderedBatchTests(unittest.TestCase):
    """Mac round-11 evidence: the Metal encoder drew every rect, then every
    circle, then every rounded rect, then every texture — z_index only ordered
    nodes *within* a kind. A CircleNode at z=12 (spotify_light's play/pause
    button) was painted over by the pill's RoundedRectNode plates at z=10, so
    the white circle read as the pill's dark tint (43,43,43) on screen while
    the CPU raster and the MCP scene readback — both z-ordered — showed white.
    The z-ordered batch planner must interleave kinds exactly like the CPU
    raster does."""

    @staticmethod
    def _frame(nodes) -> SceneFrame:
        return SceneFrame(
            logical_width=200,
            logical_height=100,
            display_width=200,
            display_height=100,
            revision=1,
            ts_ns=1,
            nodes=tuple(nodes),
        )

    def test_grouped_kind_passes_do_not_need_z_ordered_batches(self) -> None:
        frame = self._frame([
            RectNode(0, 0, 10, 10, (1, 2, 3, 255), z_index=0),
            CircleNode(5, 5, 4, (255, 255, 255, 255), z_index=1),
            RoundedRectNode(0, 0, 10, 10, 4, (9, 9, 9, 255), z_index=2),
            TextNode("hi", 0, 0, z_index=3),
        ])
        self.assertFalse(_needs_z_ordered_batches(frame))

    def test_circle_between_rounded_and_text_needs_z_ordered_batches(self) -> None:
        # The dock pattern that rendered the pause circle dark on Mac.
        frame = self._frame([
            RoundedRectNode(0, 0, 100, 40, 20, (22, 22, 22, 255), z_index=10),
            CircleNode(50, 20, 15, (225, 225, 225, 255), z_index=12),
            TextNode("||", 45, 14, z_index=13),
        ])
        self.assertTrue(_needs_z_ordered_batches(frame))

    def test_scrim_rect_over_image_needs_z_ordered_batches(self) -> None:
        # The scroll scrim (rect z=6) must cover card art (image z=3).
        frame = self._frame([
            ImageNode("art", 0, 0, 50, 50, z_index=3),
            RectNode(0, 0, 50, 8, (13, 13, 13, 200), z_index=6),
        ])
        self.assertTrue(_needs_z_ordered_batches(frame))

    def test_plan_batches_coalesces_runs_and_preserves_order(self) -> None:
        a = RectNode(0, 0, 5, 5, (1, 1, 1, 255), z_index=0)
        b = RectNode(5, 0, 5, 5, (2, 2, 2, 255), z_index=1)
        c = CircleNode(10, 10, 4, (3, 3, 3, 255), z_index=2)
        d = RectNode(0, 5, 5, 5, (4, 4, 4, 255), z_index=3)

        batches, deferred = _plan_z_ordered_batches((a, b, c, d))

        self.assertEqual(deferred, [])
        self.assertEqual([kind for kind, _ in batches], ["rect", "circle", "rect"])
        self.assertEqual(batches[0][1], (a, b))
        self.assertEqual(batches[1][1], (c,))
        self.assertEqual(batches[2][1], (d,))

    def test_plan_batches_maps_degenerate_rounded_and_solid_shader_to_rect(self) -> None:
        a = RectNode(0, 0, 5, 5, (1, 1, 1, 255), z_index=0)
        b = RoundedRectNode(5, 0, 5, 5, 0.0, (2, 2, 2, 255), z_index=1)
        c = ShaderRectNode(10, 0, 5, 5, shader="solid", color_rgba=(3, 3, 3, 255), z_index=2)

        batches, _ = _plan_z_ordered_batches((a, b, c))

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][0], "rect")
        self.assertEqual(batches[0][1], (a, b, c))

    def test_plan_batches_groups_textureish_nodes_in_order(self) -> None:
        t = TextNode("x", 0, 0, z_index=1)
        i = ImageNode("art", 0, 0, 8, 8, z_index=2)
        cpu = CpuLayerNode(0, 0, 8, 8, object(), z_index=3)

        batches, _ = _plan_z_ordered_batches((t, i, cpu))

        self.assertEqual([kind for kind, _ in batches], ["texture"])
        self.assertEqual(batches[0][1], (t, i, cpu))

    def test_plan_batches_defers_rotated_text_to_the_atlas_pass(self) -> None:
        r = TextNode("spin", 0, 0, rotation_deg=90.0, z_index=0)
        t = TextNode("flat", 0, 0, z_index=1)

        batches, deferred = _plan_z_ordered_batches((r, t))

        self.assertEqual(deferred, [r])
        self.assertEqual([kind for kind, _ in batches], ["texture"])
        self.assertEqual(batches[0][1], (t,))

    def test_cpu_raster_pins_cross_target_compositing_contract(self) -> None:
        # Spec lock: a light circle above a dark rounded plate composites over
        # it. The CPU raster is the reference the Metal target must match.
        frame = self._frame([
            RoundedRectNode(0, 0, 60, 60, 30, (22, 22, 22, 255), z_index=10),
            CircleNode(30, 30, 15, (225, 225, 225, 255), z_index=12),
        ])
        rgba = rasterize_scene_frame(frame)
        pixel = rgba[30][30]
        self.assertEqual(tuple(int(channel) for channel in pixel[:3]), (225, 225, 225))


class MacOSMetalBackingScaleTests(unittest.TestCase):
    """The app loop reads the display backing scale through the scene target so
    raster artwork can be requested at device pixels, not logical points."""

    class _Layer:
        def __init__(self) -> None:
            self.calls: dict[str, object] = {}

        def setContentsScale_(self, value) -> None:
            self.calls["contents"] = value

        def setDrawableSize_(self, size) -> None:
            self.calls["drawable"] = (float(size[0]), float(size[1]))

    class _Window:
        def __init__(self, scale: float) -> None:
            self._scale = scale

        def backingScaleFactor(self) -> float:
            return self._scale

    class _Handle:
        def __init__(self, scale: float) -> None:
            self.window = MacOSMetalBackingScaleTests._Window(scale)

    def test_resize_layer_reports_backing_scale(self) -> None:
        layer = self._Layer()
        scale = mst._resize_layer_for_window(layer, self._Handle(2.0), 1280, 800)
        self.assertEqual(scale, 2.0)
        self.assertEqual(layer.calls["contents"], 2.0)
        self.assertEqual(layer.calls["drawable"], (2560.0, 1600.0))

    def test_resize_layer_passes_size_as_a_sequence_for_pyobjc(self) -> None:
        """PyObjC depythonifies a CGSize argument from a two-element sequence;
        a hand-rolled ctypes struct raises 'depythonifying struct, got no
        sequence' (observed on the Mac, build 670b15c, Retina XDR panel —
        drawable stayed 1:1 and art rendered soft)."""

        class _PyObjCLayer:
            def __init__(self) -> None:
                self.drawable = None

            def setContentsScale_(self, value) -> None:
                pass

            def setDrawableSize_(self, size) -> None:
                if not isinstance(size, (tuple, list)):
                    raise TypeError("depythonifying struct, got no sequence")
                self.drawable = tuple(float(v) for v in size)

        layer = _PyObjCLayer()
        scale = mst._resize_layer_for_window(layer, self._Handle(2.0), 1280, 800)
        self.assertEqual(scale, 2.0)
        self.assertEqual(layer.drawable, (2560.0, 1600.0))

    def test_resize_layer_returns_none_on_failure(self) -> None:
        class _Broken:
            @property
            def window(self):
                raise RuntimeError("window gone")

        self.assertIsNone(mst._resize_layer_for_window(self._Layer(), _Broken(), 100, 100))

    def test_backend_last_backing_scale_defaults_to_one(self) -> None:
        backend = object.__new__(mst.MacOSMetalSceneBackend)
        self.assertEqual(backend.last_backing_scale, 1.0)

    def test_target_exposes_backend_backing_scale(self) -> None:
        backend = types.SimpleNamespace(last_backing_scale=2.0)
        target = mst.MacOSMetalSceneTarget(width=100, height=100, backend=backend)
        self.assertEqual(target.backing_scale(), 2.0)

    def test_target_defaults_to_one_without_backend_scale(self) -> None:
        target = mst.MacOSMetalSceneTarget(width=100, height=100, backend=types.SimpleNamespace())
        self.assertEqual(target.backing_scale(), 1.0)

    def test_resize_layer_logs_failure_reason_once(self) -> None:
        class _Broken:
            @property
            def window(self):
                raise RuntimeError("window gone")

        log_state: dict = {}
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.assertIsNone(mst._resize_layer_for_window(self._Layer(), _Broken(), 100, 100, _log_state=log_state))
            self.assertIsNone(mst._resize_layer_for_window(self._Layer(), _Broken(), 100, 100, _log_state=log_state))
        out = buf.getvalue()
        self.assertIn("layer resize failed", out)
        self.assertIn("window gone", out)
        self.assertEqual(out.count("layer resize failed"), 1)

if __name__ == "__main__":
    unittest.main()


class TestUnderGlassTransparency(unittest.TestCase):
    """SL-36: the presenter flips the window + CAMetalLayer to transparent
    only while the app clears fully transparent (under-glass live); any
    alpha keeps today's opaque compositing."""

    def test_only_fully_transparent_clear_enables_it(self):
        assert mst._under_glass_transparency((0, 0, 0, 0)) is True
        assert mst._under_glass_transparency((255, 255, 255, 0)) is True
        assert mst._under_glass_transparency((18, 18, 18, 255)) is False
        assert mst._under_glass_transparency((0, 0, 0, 1)) is False


class _FakeMainQueue:
    """Stands in for NSOperationQueue.mainQueue(): captures blocks and runs
    them under a flipped is-main flag, the way the real main queue executes
    operations on the main thread."""

    def __init__(self, thread_state: dict) -> None:
        self._thread_state = thread_state
        self.blocks: list = []

    def addOperationWithBlock_(self, block) -> None:
        self.blocks.append(block)

    def drain(self) -> None:
        while self.blocks:
            block = self.blocks.pop(0)
            self._thread_state["is_main"] = True
            try:
                block()
            finally:
                self._thread_state["is_main"] = False


class TestUnderGlassTransparencyMainThread(unittest.TestCase):
    """SL-36 Mac verify defect: present_scene runs on the render thread, and
    AppKit raised NSInternalInconsistencyException when the transparency flip
    mutated the NSWindow there ("modifying the autolayout engine from a
    background thread": setBackgroundColor -> NSThemeFrame _updateBackdropView).
    Every NSWindow/NSView mutation in the apply must run on the main thread —
    inline when already main, enqueued on the main queue otherwise."""

    def _fake_appkit(self, thread_state: dict, queue: _FakeMainQueue):
        appkit = types.ModuleType("AppKit")

        class NSThread:
            @staticmethod
            def isMainThread() -> bool:
                return bool(thread_state["is_main"])

        class NSOperationQueue:
            @staticmethod
            def mainQueue():
                return queue

        class NSColor:
            @staticmethod
            def clearColor():
                return ("clear-color",)

        appkit.NSThread = NSThread
        appkit.NSOperationQueue = NSOperationQueue
        appkit.NSColor = NSColor
        return appkit

    def _handle(self, thread_state: dict):
        class _Window:
            def __init__(self) -> None:
                self.calls: list = []
                self.original_bg = ("window-bg",)

            def backgroundColor(self):
                self.calls.append(("backgroundColor", bool(thread_state["is_main"])))
                return self.original_bg

            def setOpaque_(self, flag) -> None:
                self.calls.append(("setOpaque_", bool(thread_state["is_main"]), flag))

            def setBackgroundColor_(self, color) -> None:
                self.calls.append(("setBackgroundColor_", bool(thread_state["is_main"]), color))

        class _Layer:
            def __init__(self) -> None:
                self.calls: list = []

            def setOpaque_(self, flag) -> None:
                self.calls.append(("setOpaque_", bool(thread_state["is_main"]), flag))

        window = _Window()
        layer = _Layer()
        handle = types.SimpleNamespace(under_glass_capable=True, window=window, layer=layer)
        return handle, window, layer

    def _backend(self):
        return object.__new__(mst.MacOSMetalSceneBackend)

    def test_apply_from_render_thread_hops_to_main(self) -> None:
        thread_state = {"is_main": False}  # the render thread
        queue = _FakeMainQueue(thread_state)
        appkit = self._fake_appkit(thread_state, queue)
        handle, window, layer = self._handle(thread_state)
        backend = self._backend()
        buf = io.StringIO()
        with unittest.mock.patch.dict("sys.modules", {"AppKit": appkit}):
            with contextlib.redirect_stderr(buf):
                backend._apply_under_glass_transparency(handle, (0, 0, 0, 0))
                # Nothing may touch AppKit inline on the render thread.
                self.assertEqual(window.calls, [])
                self.assertEqual(layer.calls, [])
                self.assertEqual(len(queue.blocks), 1)
                queue.drain()
        selectors = [call[0] for call in window.calls]
        self.assertEqual(
            selectors,
            ["backgroundColor", "setOpaque_", "setBackgroundColor_"],
        )
        # Every mutation observed itself on the main thread.
        self.assertTrue(all(call[1] for call in window.calls))
        self.assertEqual(layer.calls, [("setOpaque_", True, False)])
        self.assertIn(("setOpaque_", True, False), window.calls)
        self.assertIn(("setBackgroundColor_", True, ("clear-color",)), window.calls)
        self.assertTrue(backend._under_glass_enabled)
        self.assertIn("under-glass transparency on", buf.getvalue())

    def test_apply_on_main_thread_runs_inline(self) -> None:
        thread_state = {"is_main": True}
        queue = _FakeMainQueue(thread_state)
        appkit = self._fake_appkit(thread_state, queue)
        handle, window, layer = self._handle(thread_state)
        backend = self._backend()
        buf = io.StringIO()
        with unittest.mock.patch.dict("sys.modules", {"AppKit": appkit}):
            with contextlib.redirect_stderr(buf):
                backend._apply_under_glass_transparency(handle, (0, 0, 0, 0))
        self.assertEqual(queue.blocks, [])
        self.assertEqual(
            [call[0] for call in window.calls],
            ["backgroundColor", "setOpaque_", "setBackgroundColor_"],
        )
        self.assertTrue(all(call[1] for call in window.calls))
        self.assertIn("under-glass transparency on", buf.getvalue())

    def test_restore_from_render_thread_hops_and_restores_original_bg(self) -> None:
        thread_state = {"is_main": False}
        queue = _FakeMainQueue(thread_state)
        appkit = self._fake_appkit(thread_state, queue)
        handle, window, layer = self._handle(thread_state)
        backend = self._backend()
        buf = io.StringIO()
        with unittest.mock.patch.dict("sys.modules", {"AppKit": appkit}):
            with contextlib.redirect_stderr(buf):
                backend._apply_under_glass_transparency(handle, (0, 0, 0, 0))
                queue.drain()
                self.assertTrue(backend._under_glass_enabled)
                # Glass goes away (opaque clear) from the render thread.
                backend._apply_under_glass_transparency(handle, (18, 18, 18, 255))
                self.assertEqual(len(queue.blocks), 1)
                queue.drain()
        on_calls = [call for call in window.calls if call[0] == "setOpaque_" and call[2] is False]
        off_calls = [call for call in window.calls if call[0] == "setOpaque_" and call[2] is True]
        self.assertEqual(len(on_calls), 1)
        self.assertEqual(off_calls, [("setOpaque_", True, True)])
        self.assertIn(("setBackgroundColor_", True, window.original_bg), window.calls)
        self.assertTrue(all(call[1] for call in window.calls))
        self.assertFalse(backend._under_glass_enabled)
        self.assertIn("under-glass transparency off", buf.getvalue())
