from __future__ import annotations

import ctypes
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import zlib
from dataclasses import dataclass, field

from luvatrix_core import accel
from luvatrix_core.core.debug_capture import build_screenshot_artifact_bundle
from luvatrix_core.core.debug_menu import DEFAULT_DEBUG_MENU_ACTIONS, DebugMenuDispatchResult, DebugMenuDispatcher
from luvatrix_core.core.scene_graph import (
    CircleNode,
    ClearNode,
    CpuLayerNode,
    ImageNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
    ShaderRectNode,
    TextNode,
)
from luvatrix_core.core.scene_rasterizer import _draw_layer, _draw_text, _numpy, rasterize_scene_frame
from luvatrix_core.platform.macos.metal_backend import (
    _CGSize,
    _MTL_LOAD_ACTION_CLEAR,
    _MTL_PIXEL_FORMAT_BGRA8_UNORM,
    _MTL_PIXEL_FORMAT_RGBA8_UNORM,
    _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP,
    _MTL_RESOURCE_STORAGE_MODE_SHARED,
    _MTL_STORE_ACTION_STORE,
    _MTL_TEXTURE_USAGE_SHADER_READ,
    _MTLClearColor,
    _coerce_struct,
    _create_sampler,
    _create_texture,
)
from luvatrix_core.targets.metal_target import MetalContext
from luvatrix_core.targets.scene_target import SceneRenderTarget


_MTL_PRIMITIVE_TYPE_TRIANGLE = 3
_TEXTURE_USAGE_RENDER_TARGET = 4


_SCENE_MSL = """
#include <metal_stdlib>
using namespace metal;

struct RectInstance {
    float4 rect;
    float4 color;
};

struct RectOut {
    float4 position [[position]];
    float4 color;
};

vertex RectOut rect_vertex(uint vid [[vertex_id]],
                           uint iid [[instance_id]],
                           const device RectInstance* instances [[buffer(0)]],
                           constant float4& scene_view [[buffer(1)]]) {
    constexpr float2 local[6] = {
        float2(0.0, 0.0), float2(1.0, 0.0), float2(0.0, 1.0),
        float2(1.0, 0.0), float2(1.0, 1.0), float2(0.0, 1.0),
    };
    RectInstance inst = instances[iid];
    float2 uv = local[vid];
    float2 logical_size = scene_view.xy;
    float2 px = inst.rect.xy - scene_view.zw + uv * inst.rect.zw;
    RectOut out;
    out.position = float4((px.x / logical_size.x) * 2.0 - 1.0,
                          1.0 - (px.y / logical_size.y) * 2.0,
                          0.0,
                          1.0);
    out.color = inst.color;
    return out;
}

fragment float4 rect_fragment(RectOut in [[stage_in]]) {
    return in.color;
}

struct CircleInstance {
    float4 rect;
    float4 fill_color;
    float4 stroke_color;
    float4 params;
};

struct CircleOut {
    float4 position [[position]];
    float2 uv;
    float4 fill_color;
    float4 stroke_color;
    float stroke_width;
};

vertex CircleOut circle_vertex(uint vid [[vertex_id]],
                               uint iid [[instance_id]],
                               const device CircleInstance* instances [[buffer(0)]],
                               constant float4& scene_view [[buffer(1)]]) {
    constexpr float2 local[6] = {
        float2(0.0, 0.0), float2(1.0, 0.0), float2(0.0, 1.0),
        float2(1.0, 0.0), float2(1.0, 1.0), float2(0.0, 1.0),
    };
    CircleInstance inst = instances[iid];
    float2 uv = local[vid];
    float2 logical_size = scene_view.xy;
    float2 px = inst.rect.xy - scene_view.zw + uv * inst.rect.zw;
    CircleOut out;
    out.position = float4((px.x / logical_size.x) * 2.0 - 1.0,
                          1.0 - (px.y / logical_size.y) * 2.0,
                          0.0,
                          1.0);
    out.uv = uv;
    out.fill_color = inst.fill_color;
    out.stroke_color = inst.stroke_color;
    out.stroke_width = inst.params.x;
    return out;
}

fragment float4 circle_fragment(CircleOut in [[stage_in]]) {
    float dist = length(in.uv * 2.0 - 1.0);
    float aa = max(fwidth(dist), 0.001);
    float outer = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, dist);
    if (in.stroke_width <= 0.0 || in.stroke_color.a <= 0.0) {
        return float4(in.fill_color.rgb, in.fill_color.a * outer);
    }
    float inner_edge = clamp(1.0 - in.stroke_width, 0.0, 1.0);
    float inner = 1.0 - smoothstep(inner_edge - aa, inner_edge + aa, dist);
    float stroke_alpha = outer * (1.0 - inner);
    float fill_alpha = inner;
    float4 fill = float4(in.fill_color.rgb, in.fill_color.a * fill_alpha);
    float4 stroke = float4(in.stroke_color.rgb, in.stroke_color.a * stroke_alpha);
    return mix(fill, stroke, stroke_alpha);
}

struct QuadUniforms {
    float x;
    float y;
    float width;
    float height;
    float logical_width;
    float logical_height;
    float content_offset_x;
    float content_offset_y;
};

struct QuadOut {
    float4 position [[position]];
    float2 uv;
};

vertex QuadOut textured_vertex(uint vid [[vertex_id]],
                               constant QuadUniforms& q [[buffer(0)]]) {
    constexpr float2 local[4] = {
        float2(0.0, 1.0),
        float2(1.0, 1.0),
        float2(0.0, 0.0),
        float2(1.0, 0.0),
    };
    float2 uv = local[vid];
    float2 px = float2(q.x - q.content_offset_x + uv.x * q.width,
                       q.y - q.content_offset_y + uv.y * q.height);
    QuadOut out;
    out.position = float4((px.x / q.logical_width) * 2.0 - 1.0,
                          1.0 - (px.y / q.logical_height) * 2.0,
                          0.0,
                          1.0);
    out.uv = uv;
    return out;
}

fragment float4 textured_fragment(QuadOut in [[stage_in]],
                                  texture2d<half> tex [[texture(0)]],
                                  sampler smp [[sampler(0)]]) {
    return float4(tex.sample(smp, in.uv));
}

struct GlyphOut {
    float4 position [[position]];
    float2 uv;
    float4 color;
};

vertex GlyphOut glyph_vertex(uint vid [[vertex_id]],
                             const device float4* verts [[buffer(0)]],
                             constant float2& clip_translation [[buffer(1)]]) {
    float4 a = verts[vid * 2];
    float4 b = verts[vid * 2 + 1];
    GlyphOut out;
    out.position = float4(a.x + clip_translation.x, a.y + clip_translation.y, 0.0, 1.0);
    out.uv = a.zw;
    out.color = b;
    return out;
}

fragment float4 glyph_fragment(GlyphOut in [[stage_in]],
                               texture2d<half> tex [[texture(0)]],
                               sampler smp [[sampler(0)]]) {
    float alpha = float(tex.sample(smp, in.uv).r);
    return float4(in.color.rgb, in.color.a * alpha);
}
"""


class _QuadUniforms(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
        ("logical_width", ctypes.c_float),
        ("logical_height", ctypes.c_float),
        ("content_offset_x", ctypes.c_float),
        ("content_offset_y", ctypes.c_float),
    ]


@dataclass
class _CachedTextTexture:
    texture: object
    width: int
    height: int


@dataclass
class _GlyphEntry:
    u0: float
    v0: float
    u1: float
    v1: float
    width_px: int
    height_px: int
    bearing_x: float
    bearing_y: float
    advance_px: float


@dataclass
class _GlyphAtlas:
    texture: object
    glyphs: dict[str, _GlyphEntry]
    scale: float


@dataclass
class _ReusableMetalBuffer:
    buffer: object = None
    capacity_bytes: int = 0


@dataclass
class _MacOSMetalSceneState:
    device: object
    command_queue: object
    rect_pipeline_state: object
    circle_pipeline_state: object
    textured_pipeline_state: object
    atlas_pipeline_state: object
    sampler_state: object
    window_handle: object
    window_system: object
    text_node_textures: dict[tuple[object, ...], _CachedTextTexture] = field(default_factory=dict)
    glyph_atlases: dict[tuple[str, float, float], _GlyphAtlas] = field(default_factory=dict)
    atlas_vertex_buffers: dict[tuple[object, ...], tuple[object, int]] = field(default_factory=dict)
    rect_vertex_buffers: dict[tuple[object, ...], tuple[object, int]] = field(default_factory=dict)
    circle_vertex_buffers: dict[tuple[object, ...], tuple[object, int]] = field(default_factory=dict)
    rect_stream_buffers: list[_ReusableMetalBuffer] = field(
        default_factory=lambda: [_ReusableMetalBuffer() for _ in range(3)]
    )
    circle_stream_buffers: list[_ReusableMetalBuffer] = field(
        default_factory=lambda: [_ReusableMetalBuffer() for _ in range(3)]
    )
    stream_buffer_index: int = 0
    dynamic_texture: object = None
    dynamic_texture_width: int = 0
    dynamic_texture_height: int = 0


@dataclass
class MacOSMetalSceneBackend:
    window_system: object = field(default=None)
    bar_color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)
    resizable: bool = True
    icon_path: str | None = None
    _state: _MacOSMetalSceneState | None = field(default=None, init=False, repr=False)
    _present_commits: int = field(default=0, init=False, repr=False)
    _slow_frame_count: int = field(default=0, init=False, repr=False)
    _last_frame_ms: float = field(default=0.0, init=False, repr=False)
    _last_rect_count: int = field(default=0, init=False, repr=False)
    _last_text_count: int = field(default=0, init=False, repr=False)
    _geometry_cache_hits: int = field(default=0, init=False, repr=False)
    _stream_buffer_writes: int = field(default=0, init=False, repr=False)
    _latest_frame: SceneFrame | None = field(default=None, init=False, repr=False)
    _debug_menu_app_id: str = field(default="luvatrix.app", init=False, repr=False)
    _debug_menu_profile: dict[str, object] = field(default_factory=dict, init=False, repr=False)
    _debug_menu_artifact_dir: Path = field(default=Path("artifacts/debug_menu/runtime"), init=False, repr=False)
    _debug_menu_events_path: Path = field(default=Path("artifacts/debug_menu/runtime/events.jsonl"), init=False, repr=False)
    _debug_menu_enabled: bool = field(default=True, init=False, repr=False)
    _debug_menu_functional_enabled: bool = field(default=True, init=False, repr=False)
    _debug_screenshot_count: int = field(default=0, init=False, repr=False)
    _debug_menu_dispatcher: DebugMenuDispatcher = field(default_factory=DebugMenuDispatcher, init=False, repr=False)
    _auto_capture_frame: int | None = field(default=None, init=False, repr=False)
    _auto_capture_done: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.window_system is None:
            from .window_system import AppKitWindowSystem

            self.window_system = AppKitWindowSystem()
        self._register_debug_actions()
        raw_capture_frame = os.getenv("LUVATRIX_DEBUG_SCREENSHOT_FRAME", "").strip()
        if raw_capture_frame:
            try:
                self._auto_capture_frame = max(1, int(raw_capture_frame))
            except ValueError:
                self._auto_capture_frame = None

    def initialize(self, width: int, height: int, title: str) -> MetalContext:
        import Metal

        window_handle = self.window_system.create_window(
            width,
            height,
            title,
            use_metal_layer=True,
            lock_window_size=not self.resizable,
            bar_color_rgba=self.bar_color_rgba,
            icon_path=self.icon_path,
        )
        layer = window_handle.layer
        device = Metal.MTLCreateSystemDefaultDevice()
        if device is None:
            raise RuntimeError("MTLCreateSystemDefaultDevice returned nil - no Metal GPU available")
        command_queue = device.newCommandQueue()
        if command_queue is None:
            raise RuntimeError("failed to create MTLCommandQueue")

        layer.setDevice_(device)
        layer.setPixelFormat_(_MTL_PIXEL_FORMAT_BGRA8_UNORM)
        layer.setFramebufferOnly_(False)
        try:
            layer.setAllowsNextDrawableTimeout_(False)
        except Exception:
            pass
        _resize_layer_for_window(layer, window_handle, width, height)

        self._state = _MacOSMetalSceneState(
            device=device,
            command_queue=command_queue,
            rect_pipeline_state=_compile_pipeline(device, layer, "rect_vertex", "rect_fragment"),
            circle_pipeline_state=_compile_pipeline(device, layer, "circle_vertex", "circle_fragment"),
            textured_pipeline_state=_compile_pipeline(device, layer, "textured_vertex", "textured_fragment"),
            atlas_pipeline_state=_compile_pipeline(device, layer, "glyph_vertex", "glyph_fragment"),
            sampler_state=_create_sampler(device),
            window_handle=window_handle,
            window_system=self.window_system,
        )
        print(f"[macos-metal-scene] initialized native scene target {width}x{height}", file=sys.stderr, flush=True)
        return MetalContext(width=width, height=height, title=title)

    @property
    def _window_handle(self):
        state = self._state
        return state.window_handle if state is not None else None

    def present_scene(self, context: MetalContext, frame: SceneFrame, *, target_present_time: float | None = None) -> None:
        import Metal

        state = self._state
        if state is None:
            raise RuntimeError("MacOSMetalSceneBackend is not initialized")

        self._latest_frame = frame
        started = time.perf_counter()
        _resize_layer_for_window(state.window_handle.layer, state.window_handle, context.width, context.height)
        drawable = state.window_handle.layer.nextDrawable()
        after_drawable = time.perf_counter()
        if drawable is None:
            return
        cmd = state.command_queue.commandBuffer()
        if cmd is None:
            return

        clear = _clear_color(frame, self.bar_color_rgba)
        pass_desc = Metal.MTLRenderPassDescriptor.renderPassDescriptor()
        color_attach = pass_desc.colorAttachments().objectAtIndexedSubscript_(0)
        color_attach.setTexture_(drawable.texture())
        color_attach.setLoadAction_(_MTL_LOAD_ACTION_CLEAR)
        color_attach.setStoreAction_(_MTL_STORE_ACTION_STORE)
        color_attach.setClearColor_(Metal.MTLClearColorMake(
            clear[0] / 255.0,
            clear[1] / 255.0,
            clear[2] / 255.0,
            clear[3] / 255.0,
        ))

        enc = cmd.renderCommandEncoderWithDescriptor_(pass_desc)
        after_encoder = time.perf_counter()
        after_rects = after_encoder
        after_circles = after_encoder
        after_text = after_encoder
        try:
            drawable_w, drawable_h = _drawable_size(drawable, context)
            vp_x, vp_y, vp_w, vp_h = _viewport(drawable_w, drawable_h, frame)
            enc.setViewport_((vp_x, vp_y, vp_w, vp_h, 0.0, 1.0))

            rects = _collect_rect_instances(frame)
            self._last_rect_count = len(rects)
            if rects:
                cached_rect_buffer = None
                rect_array = None
                retain_geometry = bool(frame.retained)
                if len(rects) <= 512 or retain_geometry:
                    rect_key = _rect_vertex_buffer_key(rects, frame)
                    cached_rect_buffer = state.rect_vertex_buffers.get(rect_key)
                    if cached_rect_buffer is not None:
                        self._geometry_cache_hits += 1
                if cached_rect_buffer is None:
                    rect_array = _float_array(rects, width=8)
                    if len(rects) > 512 and not retain_geometry:
                        stream_slot = state.rect_stream_buffers[state.stream_buffer_index]
                        buffer = _write_reusable_float_buffer(state.device, stream_slot, rect_array)
                        self._stream_buffer_writes += 1
                    else:
                        buffer = _new_float_buffer(state.device, rect_array)
                    if buffer is None:
                        cached_rect_buffer = None
                    else:
                        cached_rect_buffer = (buffer, len(rects))
                        if len(rects) <= 512 or retain_geometry:
                            state.rect_vertex_buffers[rect_key] = cached_rect_buffer
                            cache_limit = 32 if retain_geometry else 128
                            if len(state.rect_vertex_buffers) > cache_limit:
                                first_key = next(iter(state.rect_vertex_buffers))
                                state.rect_vertex_buffers.pop(first_key, None)
                scene_view = _scene_view_uniform(frame)
                enc.setRenderPipelineState_(state.rect_pipeline_state)
                if cached_rect_buffer is not None:
                    rect_buffer, rect_count = cached_rect_buffer
                    enc.setVertexBuffer_offset_atIndex_(rect_buffer, 0, 0)
                    _set_vertex_bytes(enc, scene_view, 1)
                    enc.drawPrimitives_vertexStart_vertexCount_instanceCount_(
                        _MTL_PRIMITIVE_TYPE_TRIANGLE,
                        0,
                        6,
                        rect_count,
                    )
            after_rects = time.perf_counter()

            circles = _collect_circle_instances(frame)
            if circles:
                cached_circle_buffer = None
                circle_key = None
                retain_geometry = bool(frame.retained)
                if len(circles) <= 512 or retain_geometry:
                    circle_key = _circle_vertex_buffer_key(circles, frame)
                    cached_circle_buffer = state.circle_vertex_buffers.get(circle_key)
                    if cached_circle_buffer is not None:
                        self._geometry_cache_hits += 1
                if cached_circle_buffer is None:
                    circle_array = (ctypes.c_float * (len(circles) * 16))()
                    i = 0
                    for circle in circles:
                        for value in circle:
                            circle_array[i] = value
                            i += 1
                    if len(circles) > 512 and not retain_geometry:
                        stream_slot = state.circle_stream_buffers[state.stream_buffer_index]
                        buffer = _write_reusable_float_buffer(state.device, stream_slot, circle_array)
                        self._stream_buffer_writes += 1
                    else:
                        buffer = _new_float_buffer(state.device, circle_array)
                    if buffer is not None:
                        cached_circle_buffer = (buffer, len(circles))
                        if circle_key is not None:
                            state.circle_vertex_buffers[circle_key] = cached_circle_buffer
                            cache_limit = 32 if retain_geometry else 128
                            if len(state.circle_vertex_buffers) > cache_limit:
                                first_key = next(iter(state.circle_vertex_buffers))
                                state.circle_vertex_buffers.pop(first_key, None)
                if cached_circle_buffer is not None:
                    scene_view = _scene_view_uniform(frame)
                    circle_buffer, circle_count = cached_circle_buffer
                    enc.setRenderPipelineState_(state.circle_pipeline_state)
                    enc.setVertexBuffer_offset_atIndex_(circle_buffer, 0, 0)
                    _set_vertex_bytes(enc, scene_view, 1)
                    enc.drawPrimitives_vertexStart_vertexCount_instanceCount_(
                        _MTL_PRIMITIVE_TYPE_TRIANGLE,
                        0,
                        6,
                        circle_count,
                    )
            after_circles = time.perf_counter()

            text_scale = _frame_scale(frame)
            text_count = _draw_atlas_text_nodes(enc, state, frame, scale=text_scale)
            enc.setRenderPipelineState_(state.textured_pipeline_state)
            enc.setFragmentSamplerState_atIndex_(state.sampler_state, 0)
            for node in frame.nodes:
                if isinstance(node, TextNode):
                    if abs(float(node.rotation_deg)) >= 0.001:
                        continue
                    texture = _cached_text_texture(state, node, scale=text_scale)
                    if texture is None:
                        continue
                    _draw_texture_quad(enc, state, texture.texture, node.x, node.y, texture.width / text_scale, texture.height / text_scale, frame)
                    text_count += 1
                elif isinstance(node, (CpuLayerNode, ImageNode)):
                    texture = _cached_dynamic_layer_texture(state, node)
                    if texture is None:
                        continue
                    _draw_texture_quad(enc, state, texture, node.x, node.y, node.width, node.height, frame)
            self._last_text_count = text_count
            after_text = time.perf_counter()
        finally:
            enc.endEncoding()
        if target_present_time is not None and target_present_time > 0.0:
            cmd.presentDrawable_atTime_(drawable, target_present_time)
        else:
            cmd.presentDrawable_(drawable)
        cmd.commit()
        state.stream_buffer_index = (state.stream_buffer_index + 1) % len(state.rect_stream_buffers)

        self._present_commits += 1
        self._maybe_auto_capture_screenshot()
        frame_ms = (time.perf_counter() - started) * 1000.0
        self._last_frame_ms = frame_ms
        if frame_ms > 50.0:
            self._slow_frame_count += 1
            if self._slow_frame_count <= 20 or self._slow_frame_count % 60 == 0:
                print(
                    f"[macos-metal-scene] slow frame #{self._slow_frame_count} "
                    f"{frame_ms:.1f}ms "
                    f"drawable={(after_drawable - started) * 1000.0:.1f} "
                    f"setup={(after_encoder - after_drawable) * 1000.0:.1f} "
                    f"rect={(after_rects - after_encoder) * 1000.0:.1f} "
                    f"circle={(after_circles - after_rects) * 1000.0:.1f} "
                    f"text={(after_text - after_circles) * 1000.0:.1f} "
                    f"rects={self._last_rect_count} text={self._last_text_count}",
                    file=sys.stderr,
                    flush=True,
                )

    def shutdown(self, context: MetalContext) -> None:
        state = self._state
        if state is None:
            return
        state.window_system.destroy_window(state.window_handle)
        self._state = None

    def pump_events(self) -> None:
        state = self._state
        if state is not None:
            state.window_system.pump_events()

    def should_close(self) -> bool:
        state = self._state
        if state is None:
            return True
        return not state.window_system.is_window_open(state.window_handle)

    def consume_telemetry(self) -> dict[str, int]:
        payload = {
            "present_commits": int(self._present_commits),
            "slow_frame_count": int(self._slow_frame_count),
            "last_frame_ms_x10": int(self._last_frame_ms * 10.0),
            "last_rect_count": int(self._last_rect_count),
            "last_text_count": int(self._last_text_count),
            "geometry_cache_hits": int(self._geometry_cache_hits),
            "stream_buffer_writes": int(self._stream_buffer_writes),
        }
        self._present_commits = 0
        self._slow_frame_count = 0
        self._geometry_cache_hits = 0
        self._stream_buffer_writes = 0
        return payload

    def configure_debug_menu(
        self,
        *,
        app_id: str,
        profile: dict[str, object],
        artifact_dir: str | Path = "artifacts/debug_menu/runtime",
        runtime_origin_refs_state_setter=None,
    ) -> None:
        _ = runtime_origin_refs_state_setter
        self._debug_menu_app_id = app_id
        self._debug_menu_profile = dict(profile)
        self._debug_menu_artifact_dir = Path(artifact_dir)
        self._debug_menu_events_path = self._debug_menu_artifact_dir / "events.jsonl"
        self._debug_menu_enabled = os.getenv("LUVATRIX_MACOS_DEBUG_MENU_WIRING", "1").strip() != "0"
        self._debug_menu_functional_enabled = os.getenv("LUVATRIX_MACOS_DEBUG_MENU_FUNCTIONAL_ACTIONS", "1").strip() != "0"
        self._write_debug_menu_manifest()

    def dispatch_debug_menu_action(self, action_id: str) -> DebugMenuDispatchResult:
        context = {
            "app_id": self._debug_menu_app_id,
            "profile": dict(self._debug_menu_profile),
            "menu_wiring_enabled": self._debug_menu_enabled,
            "functional_wiring_enabled": self._debug_menu_functional_enabled,
        }
        result = self._debug_menu_dispatcher.dispatch(action_id, context)
        self._append_debug_menu_event({"action_id": result.action_id, "status": result.status, "warning": result.warning})
        return result

    def _register_debug_actions(self) -> None:
        for spec in DEFAULT_DEBUG_MENU_ACTIONS:
            self._debug_menu_dispatcher.register(
                spec.menu_id,
                self._make_debug_handler(spec.menu_id),
                is_enabled=lambda context, action_id=spec.menu_id: self._debug_action_enabled(action_id, context),
            )

    def _debug_action_enabled(self, action_id: str, context: dict[str, object]) -> bool:
        _ = action_id
        if not bool(context.get("menu_wiring_enabled", False)):
            return False
        if not bool(context.get("functional_wiring_enabled", False)):
            return False
        profile = context.get("profile")
        if not isinstance(profile, dict):
            return False
        return bool(profile.get("supported", False)) and bool(profile.get("enable_default_debug_root", False))

    def _make_debug_handler(self, action_id: str):
        def _handler(_context: dict[str, object]) -> None:
            if action_id == "debug.menu.capture.screenshot":
                self._handle_debug_screenshot()
            elif action_id == "debug.menu.capture.screenshot.clipboard":
                self._handle_debug_screenshot()
            else:
                self._append_debug_menu_event(
                    {"action_id": action_id, "status": "HANDLER_STUBBED", "reason": "macos metal scene target supports screenshot capture"}
                )

        return _handler

    def _write_debug_menu_manifest(self) -> None:
        self._debug_menu_artifact_dir.mkdir(parents=True, exist_ok=True)
        profile_supported = bool(self._debug_menu_profile.get("supported", False)) and bool(
            self._debug_menu_profile.get("enable_default_debug_root", False)
        )
        manifest = {
            "app_id": self._debug_menu_app_id,
            "menu_wiring_enabled": bool(self._debug_menu_enabled and profile_supported),
            "functional_wiring_enabled": bool(self._debug_menu_functional_enabled),
            "profile": dict(self._debug_menu_profile),
            "actions": [spec.menu_id for spec in DEFAULT_DEBUG_MENU_ACTIONS],
        }
        (self._debug_menu_artifact_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _handle_debug_screenshot(self) -> None:
        frame = self._latest_frame
        if frame is None:
            self._append_debug_menu_event(
                {"action_id": "debug.menu.capture.screenshot", "status": "NO_FRAME"}
            )
            return
        rgba = rasterize_scene_frame(frame)
        capture_id = f"capture-{frame.revision:06d}-{self._debug_screenshot_count:03d}"
        self._debug_screenshot_count += 1
        captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        provenance_id = _frame_digest(rgba)
        bundle = build_screenshot_artifact_bundle(
            capture_id=capture_id,
            route=self._debug_menu_app_id,
            revision=str(frame.revision),
            captured_at_utc=captured_at,
            provenance_id=provenance_id,
            output_dir=str(self._debug_menu_artifact_dir / "captures"),
        )
        png_path = Path(bundle.png_path)
        sidecar_path = Path(bundle.sidecar_path)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_bytes(_encode_png_rgba_bytes(rgba))
        sidecar_path.write_text(json.dumps(bundle.sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._append_debug_menu_event(
            {
                "action_id": "debug.menu.capture.screenshot",
                "status": "HANDLER_EXECUTED",
                "capture_id": capture_id,
                "png_path": str(png_path),
                "sidecar_path": str(sidecar_path),
                "provenance_id": provenance_id,
            }
        )

    def _maybe_auto_capture_screenshot(self) -> None:
        if self._auto_capture_done or self._auto_capture_frame is None:
            return
        frame = self._latest_frame
        if frame is None or self._present_commits < self._auto_capture_frame:
            return
        self._auto_capture_done = True
        self.dispatch_debug_menu_action("debug.menu.capture.screenshot")

    def _append_debug_menu_event(self, payload: dict[str, object]) -> None:
        self._debug_menu_events_path.parent.mkdir(parents=True, exist_ok=True)
        enriched = {"ts": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), **payload}
        with self._debug_menu_events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(enriched, sort_keys=True, default=str) + "\n")


@dataclass
class MacOSMetalSceneTarget(SceneRenderTarget):
    width: int
    height: int
    backend: MacOSMetalSceneBackend
    title: str = "Luvatrix App"
    _context: MetalContext | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        if self._started:
            return
        self._context = self.backend.initialize(self.width, self.height, self.title)
        self._started = True

    def present_scene(self, frame: SceneFrame, target_present_time: float | None = None) -> None:
        if not self._started or self._context is None:
            raise RuntimeError("MacOSMetalSceneTarget must be started before presenting scenes")
        self.backend.present_scene(self._context, frame, target_present_time=target_present_time)

    def stop(self) -> None:
        if not self._started or self._context is None:
            return
        self.backend.shutdown(self._context)
        self._context = None
        self._started = False

    def pump_events(self) -> None:
        if self._started:
            self.backend.pump_events()

    def should_close(self) -> bool:
        return self._started and self.backend.should_close()

    def consume_telemetry(self) -> dict[str, int]:
        return self.backend.consume_telemetry()

    def configure_debug_menu(
        self,
        *,
        app_id: str,
        profile: dict[str, object],
        artifact_dir: str | Path = "artifacts/debug_menu/runtime",
        runtime_origin_refs_state_setter=None,
    ) -> None:
        self.backend.configure_debug_menu(
            app_id=app_id,
            profile=profile,
            artifact_dir=artifact_dir,
            runtime_origin_refs_state_setter=runtime_origin_refs_state_setter,
        )

    def dispatch_debug_menu_action(self, action_id: str) -> DebugMenuDispatchResult:
        return self.backend.dispatch_debug_menu_action(action_id)


def _compile_pipeline(device, layer, vertex_name: str, fragment_name: str) -> object:
    import Metal

    lib, err = device.newLibraryWithSource_options_error_(_SCENE_MSL, None, None)
    if lib is None:
        raise RuntimeError(f"Metal scene shader compilation failed: {err}")
    vert_fn = lib.newFunctionWithName_(vertex_name)
    frag_fn = lib.newFunctionWithName_(fragment_name)
    if vert_fn is None or frag_fn is None:
        raise RuntimeError(f"Metal scene shader functions not found: {vertex_name}/{fragment_name}")
    desc = Metal.MTLRenderPipelineDescriptor.alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    attach = desc.colorAttachments().objectAtIndexedSubscript_(0)
    attach.setPixelFormat_(layer.pixelFormat())
    attach.setBlendingEnabled_(True)
    attach.setRgbBlendOperation_(0)
    attach.setAlphaBlendOperation_(0)
    attach.setSourceRGBBlendFactor_(4)
    attach.setSourceAlphaBlendFactor_(1)
    attach.setDestinationRGBBlendFactor_(5)
    attach.setDestinationAlphaBlendFactor_(5)
    pipeline, err = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline is None:
        raise RuntimeError(f"failed to create Metal scene pipeline: {err}")
    return pipeline


def _resize_layer_for_window(layer, window_handle, width: int, height: int) -> None:
    try:
        scale = float(window_handle.window.backingScaleFactor())
        if hasattr(layer, "setContentsScale_"):
            layer.setContentsScale_(scale)
        if hasattr(layer, "setDrawableSize_"):
            layer.setDrawableSize_(_CGSize(float(width) * scale, float(height) * scale))
    except Exception:
        pass


def _drawable_size(drawable, context: MetalContext) -> tuple[float, float]:
    texture = drawable.texture()
    try:
        return float(texture.width()), float(texture.height())
    except Exception:
        return float(context.width), float(context.height)


def _viewport(drawable_w: float, drawable_h: float, frame: SceneFrame) -> tuple[float, float, float, float]:
    if getattr(frame, "presentation_mode", None) == "crop_fit":
        scale = max(drawable_w / frame.logical_width, drawable_h / frame.logical_height)
    else:
        scale = min(drawable_w / frame.logical_width, drawable_h / frame.logical_height)
    width = frame.logical_width * scale
    height = frame.logical_height * scale
    return ((drawable_w - width) / 2.0, (drawable_h - height) / 2.0, width, height)


def _frame_scale(frame: SceneFrame) -> float:
    return min(
        float(frame.display_width) / max(1.0, float(frame.logical_width)),
        float(frame.display_height) / max(1.0, float(frame.logical_height)),
    )


def _clear_color(frame: SceneFrame, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    for node in frame.nodes:
        if isinstance(node, ClearNode):
            return node.color_rgba
    return fallback


def _collect_rect_instances(frame: SceneFrame) -> list[tuple[float, float, float, float, float, float, float, float]]:
    out: list[tuple[float, float, float, float, float, float, float, float]] = []
    for node in frame.nodes:
        if isinstance(node, RectNode):
            out.append(_rect_instance(node.x, node.y, node.width, node.height, node.color_rgba))
        elif isinstance(node, RoundedRectNode):
            out.append(_rect_instance(node.x, node.y, node.width, node.height, node.color_rgba))
        elif isinstance(node, ShaderRectNode) and node.shader == "solid":
            out.append(_rect_instance(node.x, node.y, node.width, node.height, node.color_rgba))
    return out


def _collect_circle_instances(frame: SceneFrame) -> list[tuple[float, ...]]:
    out: list[tuple[float, ...]] = []
    for node in frame.nodes:
        if not isinstance(node, CircleNode):
            continue
        radius = float(node.radius)
        stroke_width = float(node.stroke_width) / max(1.0, radius)
        out.append(
            (
                float(node.cx) - radius,
                float(node.cy) - radius,
                radius * 2.0,
                radius * 2.0,
                node.fill_rgba[0] / 255.0,
                node.fill_rgba[1] / 255.0,
                node.fill_rgba[2] / 255.0,
                node.fill_rgba[3] / 255.0,
                node.stroke_rgba[0] / 255.0,
                node.stroke_rgba[1] / 255.0,
                node.stroke_rgba[2] / 255.0,
                node.stroke_rgba[3] / 255.0,
                stroke_width,
                0.0,
                0.0,
                0.0,
            )
        )
    return out


def _rect_instance(
    x: float,
    y: float,
    width: float,
    height: float,
    color: tuple[int, int, int, int],
) -> tuple[float, float, float, float, float, float, float, float]:
    return (
        float(x),
        float(y),
        float(width),
        float(height),
        color[0] / 255.0,
        color[1] / 255.0,
        color[2] / 255.0,
        color[3] / 255.0,
    )


def _rect_vertex_buffer_key(
    rects: list[tuple[float, float, float, float, float, float, float, float]],
    frame: SceneFrame,
) -> tuple[object, ...]:
    return (
        round(float(frame.logical_width), 3),
        round(float(frame.logical_height), 3),
        tuple(tuple(round(value, 3) for value in rect) for rect in rects),
    )


def _float_array(rows: list[tuple[float, ...]], *, width: int):
    out = (ctypes.c_float * (len(rows) * width))()
    i = 0
    for row in rows:
        for value in row:
            out[i] = value
            i += 1
    return out


def _new_float_buffer(device, values):
    payload = bytes(values)
    return device.newBufferWithBytes_length_options_(payload, len(payload), 0)


def _write_reusable_float_buffer(device, slot: _ReusableMetalBuffer, values):
    payload = bytes(values)
    required = len(payload)
    if required <= 0:
        return None
    if slot.buffer is None or slot.capacity_bytes < required:
        capacity = 1 << max(12, (required - 1).bit_length())
        slot.buffer = device.newBufferWithLength_options_(capacity, _MTL_RESOURCE_STORAGE_MODE_SHARED)
        slot.capacity_bytes = capacity if slot.buffer is not None else 0
    if slot.buffer is None:
        return None
    contents = slot.buffer.contents()
    if hasattr(contents, "as_buffer"):
        contents.as_buffer(required)[:required] = payload
    else:
        ctypes.memmove(contents, payload, required)
    return slot.buffer


def _set_vertex_bytes(enc, values, index: int) -> None:
    payload = bytes(values)
    enc.setVertexBytes_length_atIndex_(payload, len(payload), index)


def _scene_view_uniform(frame: SceneFrame):
    return (ctypes.c_float * 4)(
        float(frame.logical_width),
        float(frame.logical_height),
        float(frame.content_offset_x),
        float(frame.content_offset_y),
    )


def _circle_vertex_buffer_key(
    circles: list[tuple[float, ...]],
    frame: SceneFrame,
) -> tuple[object, ...]:
    return (
        round(float(frame.logical_width), 3),
        round(float(frame.logical_height), 3),
        tuple(tuple(round(value, 3) for value in circle) for circle in circles),
    )


def _draw_texture_quad(enc, state: _MacOSMetalSceneState, texture, x: float, y: float, width: float, height: float, frame: SceneFrame) -> None:
    quad = _QuadUniforms(
        float(x),
        float(y),
        float(width),
        float(height),
        float(frame.logical_width),
        float(frame.logical_height),
        float(frame.content_offset_x),
        float(frame.content_offset_y),
    )
    _set_vertex_bytes(enc, quad, 0)
    enc.setFragmentTexture_atIndex_(texture, 0)
    enc.drawPrimitives_vertexStart_vertexCount_(_MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP, 0, 4)


def _cached_text_texture(state: _MacOSMetalSceneState, node: TextNode, *, scale: float) -> _CachedTextTexture | None:
    key = _text_node_texture_key(node, scale)
    cached = state.text_node_textures.get(key)
    if cached is not None:
        return cached
    rgba = _rasterize_text_node(node, scale=scale)
    if rgba is None:
        return None
    h, w, _ = rgba.shape
    texture = _create_texture(state.device, w, h)
    payload = _rgba_payload_bytes(rgba)
    texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
        _texture_region(w, h),
        0,
        payload,
        w * 4,
    )
    cached = _CachedTextTexture(texture=texture, width=w, height=h)
    state.text_node_textures[key] = cached
    if len(state.text_node_textures) > 512:
        first_key = next(iter(state.text_node_textures))
        state.text_node_textures.pop(first_key, None)
    return cached


def _draw_atlas_text_nodes(enc, state: _MacOSMetalSceneState, frame: SceneFrame, *, scale: float) -> int:
    nodes = [
        node for node in frame.nodes
        if isinstance(node, TextNode)
        and node.text
        and node.color_rgba[3] > 0
        and abs(float(node.rotation_deg)) >= 0.001
    ]
    if not nodes:
        return 0
    groups: dict[tuple[str, float], list[TextNode]] = {}
    for node in nodes:
        groups.setdefault((node.font_family, round(float(node.font_size_px), 3)), []).append(node)

    total_nodes = 0
    enc.setRenderPipelineState_(state.atlas_pipeline_state)
    enc.setFragmentSamplerState_atIndex_(state.sampler_state, 0)
    clip_translation = (ctypes.c_float * 2)(
        -2.0 * float(frame.content_offset_x) / max(1.0, float(frame.logical_width)),
        2.0 * float(frame.content_offset_y) / max(1.0, float(frame.logical_height)),
    )
    _set_vertex_bytes(enc, clip_translation, 1)
    for (font_family, font_size_px), group in groups.items():
        atlas = _glyph_atlas(state, font_family, font_size_px, scale)
        if atlas is None:
            continue
        buffer_key = _atlas_vertex_buffer_key(group, frame, scale)
        cached_buffer = state.atlas_vertex_buffers.get(buffer_key)
        if cached_buffer is None:
            owner = _atlas_vertex_buffer(group, atlas, frame, scale)
            if owner is None:
                continue
            vertex_count = int(len(owner) // 8)
            if vertex_count <= 0:
                continue
            buffer = _new_float_buffer(state.device, owner)
            if buffer is None:
                continue
            cached_buffer = (buffer, vertex_count)
            state.atlas_vertex_buffers[buffer_key] = cached_buffer
            if len(state.atlas_vertex_buffers) > 128:
                first_key = next(iter(state.atlas_vertex_buffers))
                state.atlas_vertex_buffers.pop(first_key, None)
        buffer, vertex_count = cached_buffer
        if vertex_count <= 0:
            continue
        enc.setVertexBuffer_offset_atIndex_(buffer, 0, 0)
        enc.setFragmentTexture_atIndex_(atlas.texture, 0)
        enc.drawPrimitives_vertexStart_vertexCount_(_MTL_PRIMITIVE_TYPE_TRIANGLE, 0, vertex_count)
        total_nodes += len(group)
    return total_nodes


def _glyph_atlas(state: _MacOSMetalSceneState, font_family: str, font_size_px: float, scale: float) -> _GlyphAtlas | None:
    key = (font_family, round(float(font_size_px), 3), round(float(scale), 3))
    cached = state.glyph_atlases.get(key)
    if cached is not None:
        return cached
    try:
        from PIL import Image, ImageDraw
        from luvatrix_core.core.ui_frame_renderer import _load_font, _resolve_system_font_path

        font = _load_font(_resolve_system_font_path(font_family), max(1.0, font_size_px * scale))
        charset = "".join(chr(code) for code in range(32, 127))
        entries_raw: list[tuple[str, int, int, int, int, float]] = []
        row_height = 1
        for ch in charset:
            left, top, right, bottom = font.getbbox(ch)
            width = max(1, int(math.ceil(right - left)))
            height = max(1, int(math.ceil(bottom - top)))
            row_height = max(row_height, height + 2)
            entries_raw.append((ch, width, height, left, top, float(font.getlength(ch))))

        atlas_w = 1024
        pad = 2
        x = 0
        y = 0
        packed: list[tuple[str, int, int, int, int, int, int, float]] = []
        for ch, width, height, bearing_x, bearing_y, advance in entries_raw:
            if x + width + pad > atlas_w:
                x = 0
                y += row_height
            packed.append((ch, x, y, width, height, bearing_x, bearing_y, advance))
            x += width + pad
        atlas_h = max(1, y + row_height)
        image = Image.new("L", (atlas_w, atlas_h), 0)
        draw = ImageDraw.Draw(image)
        for ch, px, py, width, height, bearing_x, bearing_y, advance in packed:
            draw.text((px - bearing_x, py - bearing_y), ch, fill=255, font=font)
        rgba = Image.merge("RGBA", (image, image, image, image))
        texture = _create_texture(state.device, atlas_w, atlas_h)
        data = rgba.tobytes()
        texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
            _texture_region(atlas_w, atlas_h),
            0,
            data,
            atlas_w * 4,
        )
        glyphs: dict[str, _GlyphEntry] = {}
        for ch, px, py, width, height, bearing_x, bearing_y, advance in packed:
            glyphs[ch] = _GlyphEntry(
                u0=float(px) / float(atlas_w),
                v0=float(py) / float(atlas_h),
                u1=float(px + width) / float(atlas_w),
                v1=float(py + height) / float(atlas_h),
                width_px=width,
                height_px=height,
                bearing_x=float(bearing_x),
                bearing_y=float(bearing_y),
                advance_px=float(advance),
            )
        atlas = _GlyphAtlas(texture=texture, glyphs=glyphs, scale=scale)
        state.glyph_atlases[key] = atlas
        if len(state.glyph_atlases) > 32:
            first_key = next(iter(state.glyph_atlases))
            state.glyph_atlases.pop(first_key, None)
        return atlas
    except Exception as exc:
        print(f"[macos-metal-scene] glyph atlas unavailable: {exc}", file=sys.stderr, flush=True)
        return None


def _atlas_vertex_buffer(nodes: list[TextNode], atlas: _GlyphAtlas, frame: SceneFrame, scale: float):
    floats: list[float] = []
    inv_scale = 1.0 / max(0.001, scale)
    inv_lw = 2.0 / max(1.0, float(frame.logical_width))
    inv_lh = 2.0 / max(1.0, float(frame.logical_height))
    for node in nodes:
        cursor_x = float(node.x)
        pen_y = float(node.y)
        rotation = math.radians(float(node.rotation_deg))
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        origin_x = float(node.x)
        origin_y = float(node.y)
        r, g, b, a = (node.color_rgba[0] / 255.0, node.color_rgba[1] / 255.0, node.color_rgba[2] / 255.0, node.color_rgba[3] / 255.0)
        for ch in node.text:
            glyph = atlas.glyphs.get(ch)
            if glyph is None:
                cursor_x += float(node.font_size_px) * 0.45
                continue
            x0 = cursor_x + glyph.bearing_x * inv_scale
            y0 = pen_y + glyph.bearing_y * inv_scale
            x1 = x0 + glyph.width_px * inv_scale
            y1 = y0 + glyph.height_px * inv_scale
            p00 = _clip_point(x0, y0, origin_x, origin_y, cos_r, sin_r, inv_lw, inv_lh)
            p10 = _clip_point(x1, y0, origin_x, origin_y, cos_r, sin_r, inv_lw, inv_lh)
            p01 = _clip_point(x0, y1, origin_x, origin_y, cos_r, sin_r, inv_lw, inv_lh)
            p11 = _clip_point(x1, y1, origin_x, origin_y, cos_r, sin_r, inv_lw, inv_lh)
            _append_glyph_vertex(floats, p00[0], p00[1], glyph.u0, glyph.v0, r, g, b, a)
            _append_glyph_vertex(floats, p10[0], p10[1], glyph.u1, glyph.v0, r, g, b, a)
            _append_glyph_vertex(floats, p01[0], p01[1], glyph.u0, glyph.v1, r, g, b, a)
            _append_glyph_vertex(floats, p10[0], p10[1], glyph.u1, glyph.v0, r, g, b, a)
            _append_glyph_vertex(floats, p11[0], p11[1], glyph.u1, glyph.v1, r, g, b, a)
            _append_glyph_vertex(floats, p01[0], p01[1], glyph.u0, glyph.v1, r, g, b, a)
            cursor_x += glyph.advance_px * inv_scale
    if not floats:
        return None
    return (ctypes.c_float * len(floats))(*floats)


def _atlas_vertex_buffer_key(nodes: list[TextNode], frame: SceneFrame, scale: float) -> tuple[object, ...]:
    items: list[object] = [
        round(float(scale), 3),
        round(float(frame.logical_width), 3),
        round(float(frame.logical_height), 3),
    ]
    for node in nodes:
        items.append(
            (
                node.text,
                round(float(node.x), 2),
                round(float(node.y), 2),
                node.font_family,
                round(float(node.font_size_px), 3),
                node.color_rgba,
                None if node.max_width_px is None else round(float(node.max_width_px), 2),
                round(float(node.rotation_deg), 2),
                node.cache_key,
            )
        )
    return tuple(items)


def _clip_point(
    x: float,
    y: float,
    origin_x: float,
    origin_y: float,
    cos_r: float,
    sin_r: float,
    inv_lw: float,
    inv_lh: float,
) -> tuple[float, float]:
    dx = x - origin_x
    dy = y - origin_y
    rx = origin_x + dx * cos_r - dy * sin_r
    ry = origin_y + dx * sin_r + dy * cos_r
    return (rx * inv_lw - 1.0, 1.0 - ry * inv_lh)


def _append_glyph_vertex(
    floats: list[float],
    x: float,
    y: float,
    u: float,
    v: float,
    r: float,
    g: float,
    b: float,
    a: float,
) -> None:
    floats.extend((x, y, u, v, r, g, b, a))


def _rasterize_text_node(node: TextNode, *, scale: float):
    np = _numpy()
    if np is None or not node.text or node.color_rgba[3] <= 0:
        return None
    try:
        from PIL import Image, ImageDraw
        from luvatrix_core.core.ui_frame_renderer import _load_font, _resolve_system_font_path

        font = _load_font(_resolve_system_font_path(node.font_family), max(1.0, node.font_size_px * scale))
        bbox = font.getbbox(node.text)
        left, top, right, bottom = bbox
        width = max(1, int(math.ceil(right - left)))
        height = max(1, int(math.ceil(bottom - top)))
        image = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(image)
        draw.text((-left, -top), node.text, fill=255, font=font)
        if node.rotation_deg:
            image = image.rotate(float(node.rotation_deg), resample=Image.Resampling.BICUBIC, expand=True)
        mask = np.asarray(image, dtype=np.uint8)
    except Exception:
        width = max(1, int(round(len(node.text) * node.font_size_px * scale * 0.75)))
        height = max(1, int(round(node.font_size_px * scale * 1.25)))
        out = np.zeros((height, width, 4), dtype=np.uint8)
        _draw_text(
            out,
            TextNode(
                node.text,
                x=0,
                y=0,
                font_family=node.font_family,
                font_size_px=node.font_size_px,
                color_rgba=node.color_rgba,
                rotation_deg=node.rotation_deg,
            ),
            sx=scale,
            sy=scale,
        )
        return out

    out = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
    out[:, :, 0] = node.color_rgba[0]
    out[:, :, 1] = node.color_rgba[1]
    out[:, :, 2] = node.color_rgba[2]
    out[:, :, 3] = ((mask.astype(np.float32) / 255.0) * float(node.color_rgba[3])).astype(np.uint8)
    return out


def _text_node_texture_key(node: TextNode, scale: float) -> tuple[object, ...]:
    return (
        node.cache_key,
        node.text,
        node.font_family,
        round(float(node.font_size_px), 3),
        node.color_rgba,
        None if node.max_width_px is None else round(float(node.max_width_px), 3),
        round(float(node.rotation_deg), 3),
        round(float(scale), 3),
    )


def _cached_dynamic_layer_texture(state: _MacOSMetalSceneState, node: CpuLayerNode | ImageNode):
    rgba = node.rgba
    if rgba is None:
        return None
    if isinstance(node, ImageNode):
        np = _numpy()
        if np is None:
            return None
        overlay = np.zeros((max(1, int(node.height)), max(1, int(node.width)), 4), dtype=np.uint8)
        _draw_layer(overlay, CpuLayerNode(0, 0, node.width, node.height, rgba, node.z_index), sx=1.0, sy=1.0)
        rgba = overlay
    h, w, _ = rgba.shape
    if state.dynamic_texture is None or state.dynamic_texture_width != w or state.dynamic_texture_height != h:
        state.dynamic_texture = _create_texture(state.device, w, h)
        state.dynamic_texture_width = w
        state.dynamic_texture_height = h
    payload = _rgba_payload_bytes(rgba)
    state.dynamic_texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
        _texture_region(w, h),
        0,
        payload,
        w * 4,
    )
    return state.dynamic_texture


def _texture_region(width: int, height: int):
    return ((0, 0, 0), (int(width), int(height), 1))


def _frame_digest(rgba) -> str:
    return hashlib.sha256(_rgba_bytes(rgba)).hexdigest()


def _encode_png_rgba_bytes(rgba) -> bytes:
    height, width, channels = rgba.shape
    if int(channels) != 4:
        raise ValueError("expected RGBA image with 4 channels")
    rows = _rgba_row_bytes(rgba)
    raw = b"".join(b"\x00" + row for row in rows)
    payload = zlib.compress(raw)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big")
            + chunk_type
            + data
            + zlib.crc32(chunk_type + data).to_bytes(4, "big")
        )

    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", int(width).to_bytes(4, "big") + int(height).to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])),
            _chunk(b"IDAT", payload),
            _chunk(b"IEND", b""),
        )
    )


def _rgba_bytes(rgba) -> bytes:
    return b"".join(_rgba_row_bytes(rgba))


def _rgba_row_bytes(rgba) -> list[bytes]:
    if hasattr(rgba, "contiguous") and hasattr(rgba, "cpu"):
        arr = rgba.contiguous().cpu().numpy()
        return [arr[row].tobytes() for row in range(arr.shape[0])]
    if hasattr(rgba, "tobytes") and hasattr(rgba, "shape"):
        return [rgba[row].tobytes() for row in range(rgba.shape[0])]
    if hasattr(rgba, "_data") and hasattr(rgba, "shape"):
        height, width, channels = rgba.shape
        stride = int(width) * int(channels)
        data = bytes(rgba._data)  # noqa: SLF001 - pure-array debug serialization
        return [data[row * stride : (row + 1) * stride] for row in range(int(height))]
    raise TypeError(f"unsupported RGBA buffer type for screenshot: {type(rgba)!r}")


def _upload_owner_and_pointer(rgba) -> tuple[object, object]:
    if hasattr(rgba, "data_ptr") and callable(rgba.data_ptr):
        owner = rgba.contiguous() if hasattr(rgba, "contiguous") else rgba
        return owner, ctypes.c_void_p(int(owner.data_ptr()))
    ctypes_view = getattr(rgba, "ctypes", None)
    if ctypes_view is not None and hasattr(ctypes_view, "data_as"):
        return rgba, ctypes_view.data_as(ctypes.c_void_p)
    owner = accel.to_contiguous_numpy(rgba)
    return owner, owner.ctypes.data_as(ctypes.c_void_p)


def _rgba_payload_bytes(rgba) -> bytes:
    if hasattr(rgba, "contiguous") and hasattr(rgba, "cpu"):
        return rgba.contiguous().cpu().numpy().tobytes(order="C")
    if hasattr(rgba, "tobytes"):
        return rgba.tobytes(order="C")
    if hasattr(rgba, "_data"):
        return bytes(rgba._data)  # noqa: SLF001 - pure-array texture upload
    owner = accel.to_contiguous_numpy(rgba)
    return owner.tobytes(order="C")
