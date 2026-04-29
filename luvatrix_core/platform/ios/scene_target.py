from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import math
import sys
import time

from luvatrix_core import accel
from luvatrix_core.core.scene_graph import (
    CircleNode,
    ClearNode,
    CpuLayerNode,
    ImageNode,
    RectNode,
    SceneFrame,
    ShaderRectNode,
    SvgNode,
    TextNode,
)
from luvatrix_core.core.scene_rasterizer import _draw_circle, _draw_layer, _draw_rect, _draw_text, _numpy
from luvatrix_core.platform.ios.metal_backend import (
    _CGSize,
    _MTL_LOAD_ACTION_CLEAR,
    _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP,
    _MTL_STORE_ACTION_STORE,
    _MTLClearColor,
    _MTLViewport,
    _coerce_struct,
    _create_sampler,
    _create_texture,
    _ios_app_active,
    _metal_lib,
    _next_drawable_gil_free,
)
from luvatrix_core.targets.metal_target import MetalContext


_SCENE_MSL_SOURCE = """
#include <metal_stdlib>
using namespace metal;

struct VertexOut {
    float4 position [[position]];
    float2 uv;
};

struct SceneUniforms {
    float t;
    float rotation;
    float scroll_y;
    float pad;
};

vertex VertexOut scene_vertex(uint vid [[vertex_id]]) {
    constexpr float2 positions[4] = {
        float2(-1.0, -1.0),
        float2( 1.0, -1.0),
        float2(-1.0,  1.0),
        float2( 1.0,  1.0),
    };
    constexpr float2 uvs[4] = {
        float2(0.0, 1.0),
        float2(1.0, 1.0),
        float2(0.0, 0.0),
        float2(1.0, 0.0),
    };
    VertexOut out;
    out.position = float4(positions[vid], 0.0, 1.0);
    out.uv = uvs[vid];
    return out;
}

fragment float4 full_suite_fragment(VertexOut in [[stage_in]],
                                    constant SceneUniforms& u [[buffer(0)]]) {
    int ti = int(u.t);
    float base_r = float((ti * 3 + 35) % 255);
    float base_g = float((ti * 2 + 70) % 255);
    float base_b = float((ti * 4 + 20) % 255);
    float rotate_boost = clamp(u.rotation * 2.0, -30.0, 30.0);
    float scroll_boost = clamp(u.scroll_y * 0.5, -40.0, 40.0);
    return float4(
        clamp(base_r + rotate_boost, 0.0, 255.0) / 255.0,
        clamp(base_g + scroll_boost, 0.0, 255.0) / 255.0,
        clamp(base_b, 0.0, 255.0) / 255.0,
        1.0
    );
}
"""

_OVERLAY_MSL_SOURCE = """
#include <metal_stdlib>
using namespace metal;

struct VertexOut {
    float4 position [[position]];
    float2 uv;
};

vertex VertexOut overlay_vertex(uint vid [[vertex_id]]) {
    constexpr float2 positions[4] = {
        float2(-1.0, -1.0),
        float2( 1.0, -1.0),
        float2(-1.0,  1.0),
        float2( 1.0,  1.0),
    };
    constexpr float2 uvs[4] = {
        float2(0.0, 1.0),
        float2(1.0, 1.0),
        float2(0.0, 0.0),
        float2(1.0, 0.0),
    };
    VertexOut out;
    out.position = float4(positions[vid], 0.0, 1.0);
    out.uv = uvs[vid];
    return out;
}

fragment float4 overlay_fragment(VertexOut in [[stage_in]],
                                  texture2d<half> tex [[texture(0)]],
                                  sampler smp [[sampler(0)]]) {
    return float4(tex.sample(smp, in.uv));
}
"""

_PRIMITIVE_MSL_SOURCE = """
#include <metal_stdlib>
using namespace metal;

struct VertexOut {
    float4 position [[position]];
    float2 uv;
};

struct QuadUniforms {
    float x;
    float y;
    float width;
    float height;
    float logical_width;
    float logical_height;
};

struct PrimitiveUniforms {
    float4 color;
    float4 stroke_color;
    float stroke_width;
    float shape;
    float pad0;
    float pad1;
};

vertex VertexOut primitive_vertex(uint vid [[vertex_id]],
                                  constant QuadUniforms& q [[buffer(0)]]) {
    constexpr float2 local[4] = {
        float2(0.0, 1.0),
        float2(1.0, 1.0),
        float2(0.0, 0.0),
        float2(1.0, 0.0),
    };
    float2 uv = local[vid];
    float px = q.x + uv.x * q.width;
    float py = q.y + uv.y * q.height;
    VertexOut out;
    out.position = float4((px / q.logical_width) * 2.0 - 1.0,
                          1.0 - (py / q.logical_height) * 2.0,
                          0.0,
                          1.0);
    out.uv = uv;
    return out;
}

fragment float4 primitive_fragment(VertexOut in [[stage_in]],
                                   constant PrimitiveUniforms& p [[buffer(0)]]) {
    if (p.shape < 0.5) {
        return p.color;
    }
    float2 centered = in.uv * 2.0 - 1.0;
    float dist = length(centered);
    float aa = fwidth(dist);
    float fill_alpha = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, dist);
    float4 out_color = p.color;
    out_color.a *= fill_alpha;
    if (p.stroke_width > 0.0 && p.stroke_color.a > 0.0) {
        float stroke_norm = clamp(p.stroke_width, 0.0, 1.0);
        float stroke_alpha = smoothstep(1.0 - stroke_norm - aa, 1.0 - stroke_norm, dist)
                           * (1.0 - smoothstep(1.0 - aa, 1.0 + aa, dist));
        out_color = mix(out_color, p.stroke_color, stroke_alpha * p.stroke_color.a);
    }
    return out_color;
}

fragment float4 textured_fragment(VertexOut in [[stage_in]],
                                  texture2d<half> tex [[texture(0)]],
                                  sampler smp [[sampler(0)]]) {
    return float4(tex.sample(smp, in.uv));
}
"""


class _SceneUniforms(ctypes.Structure):
    _fields_ = [
        ("t", ctypes.c_float),
        ("rotation", ctypes.c_float),
        ("scroll_y", ctypes.c_float),
        ("pad", ctypes.c_float),
    ]


class _QuadUniforms(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
        ("logical_width", ctypes.c_float),
        ("logical_height", ctypes.c_float),
    ]


class _PrimitiveUniforms(ctypes.Structure):
    _fields_ = [
        ("r", ctypes.c_float),
        ("g", ctypes.c_float),
        ("b", ctypes.c_float),
        ("a", ctypes.c_float),
        ("sr", ctypes.c_float),
        ("sg", ctypes.c_float),
        ("sb", ctypes.c_float),
        ("sa", ctypes.c_float),
        ("stroke_width", ctypes.c_float),
        ("shape", ctypes.c_float),
        ("pad0", ctypes.c_float),
        ("pad1", ctypes.c_float),
    ]


@dataclass
class _CachedTextTexture:
    texture: object
    width: int
    height: int


@dataclass
class _IOSMetalSceneState:
    device: object
    command_queue: object
    scene_pipeline_state: object
    overlay_pipeline_state: object
    primitive_pipeline_state: object
    textured_quad_pipeline_state: object
    sampler_state: object
    window_handle: object
    window_system: object
    overlay_texture: object = None
    overlay_texture_width: int = 0
    overlay_texture_height: int = 0
    text_texture: object = None
    text_texture_width: int = 0
    text_texture_height: int = 0
    text_signature: tuple[object, ...] | None = None
    dynamic_texture: object = None
    dynamic_texture_width: int = 0
    dynamic_texture_height: int = 0
    text_node_textures: dict[tuple[object, ...], _CachedTextTexture] = field(default_factory=dict)


@dataclass
class IOSMetalSceneBackend:
    window_system: object
    bar_color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255)
    _state: _IOSMetalSceneState | None = field(default=None, init=False, repr=False)
    _was_inactive: bool = field(default=False, init=False, repr=False)
    _next_drawable_nil: int = field(default=0, init=False, repr=False)
    _next_drawable_slow: int = field(default=0, init=False, repr=False)
    _present_commits: int = field(default=0, init=False, repr=False)

    def initialize(self, width: int, height: int, title: str) -> MetalContext:
        from rubicon.objc.api import ObjCInstance

        window_handle = self.window_system.create_window(
            width, height, title, use_metal_layer=True, preserve_aspect_ratio=False
        )
        layer = window_handle.layer

        raw_ptr = _metal_lib().MTLCreateSystemDefaultDevice()
        if not raw_ptr:
            raise RuntimeError("MTLCreateSystemDefaultDevice returned nil")
        device = ObjCInstance(ctypes.c_void_p(raw_ptr))
        command_queue = device.newCommandQueue()
        if command_queue is None:
            raise RuntimeError("newCommandQueue returned nil")

        layer.setDevice_(device)
        layer.setPixelFormat_(80)
        layer.setFramebufferOnly_(False)
        layer.setAllowsNextDrawableTimeout_(False)

        set_size = layer.setDrawableSize_

        layer.setDrawableSize_(_coerce_struct(set_size, 0, _CGSize(float(width), float(height))))

        self._state = _IOSMetalSceneState(
            device=device,
            command_queue=command_queue,
            scene_pipeline_state=_compile_scene_pipeline(device, layer),
            overlay_pipeline_state=_compile_overlay_pipeline(device, layer),
            primitive_pipeline_state=_compile_primitive_pipeline(device, layer),
            textured_quad_pipeline_state=_compile_textured_quad_pipeline(device, layer),
            sampler_state=_create_sampler(device),
            window_handle=window_handle,
            window_system=self.window_system,
        )
        return MetalContext(width=width, height=height, title=title)

    def present_scene(self, context: MetalContext, frame: SceneFrame) -> None:
        from rubicon.objc import ObjCClass

        s = self._state
        if s is None:
            raise RuntimeError("IOSMetalSceneBackend is not initialized")

        # iOS can throttle/block drawable acquisition while inactive. Skip
        # compositor work entirely, then refresh layer settings on foreground.
        app_active = _ios_app_active()
        if not app_active:
            self._was_inactive = True
            return
        elif self._was_inactive:
            self._was_inactive = False
            try:
                s.window_handle.layer.setAllowsNextDrawableTimeout_(False)
                set_size = s.window_handle.layer.setDrawableSize_
                s.window_handle.layer.setDrawableSize_(
                    _coerce_struct(set_size, 0, _CGSize(float(context.width), float(context.height)))
                )
                print("[ios-metal] restored scene layer after foreground", file=sys.stderr, flush=True)
            except Exception as _exc:
                print(f"[ios-metal] scene restore failed: {_exc}", file=sys.stderr, flush=True)

        t_pre = time.perf_counter()
        drawable = _next_drawable_gil_free(s.window_handle.layer)
        t_post = time.perf_counter()
        if drawable is None:
            self._next_drawable_nil += 1
            if t_post - t_pre > 0.010:
                self._next_drawable_slow += 1
                print(f"[ios-metal] nextDrawable blocked {(t_post - t_pre) * 1000:.0f}ms → nil", file=sys.stderr, flush=True)
            time.sleep(0.004)
            return
        if t_post - t_pre > 0.010:
            self._next_drawable_slow += 1
            print(f"[ios-metal] nextDrawable slow: {(t_post - t_pre) * 1000:.0f}ms", file=sys.stderr, flush=True)
        cmd = s.command_queue.commandBuffer()
        if cmd is None:
            return

        scale = min(context.width / frame.logical_width, context.height / frame.logical_height)
        vp_w = frame.logical_width * scale
        vp_h = frame.logical_height * scale
        vp_x = (context.width - vp_w) / 2.0
        vp_y = (context.height - vp_h) / 2.0

        pass_desc = ObjCClass("MTLRenderPassDescriptor").renderPassDescriptor()
        color_attach = pass_desc.colorAttachments.objectAtIndexedSubscript_(0)
        color_attach.setTexture_(drawable.texture)
        color_attach.setLoadAction_(_MTL_LOAD_ACTION_CLEAR)
        color_attach.setStoreAction_(_MTL_STORE_ACTION_STORE)
        bar = self.bar_color_rgba
        color_attach.setClearColor_(
            _coerce_struct(
                color_attach.setClearColor_,
                0,
                _MTLClearColor(
                    red=bar[0] / 255.0,
                    green=bar[1] / 255.0,
                    blue=bar[2] / 255.0,
                    alpha=bar[3] / 255.0,
                ),
            )
        )

        enc = cmd.renderCommandEncoderWithDescriptor_(pass_desc)
        enc.setViewport_(_coerce_struct(enc.setViewport_, 0, _MTLViewport(vp_x, vp_y, vp_w, vp_h, 0.0, 1.0)))

        shader = _first_background_shader(frame)
        if shader is not None:
            shader_t = time.perf_counter() * 120.0 if shader.shader == "full_suite_background" else (
                float(shader.uniforms[0]) if shader.uniforms else 0.0
            )
            uniforms = _SceneUniforms(
                shader_t,
                float(shader.uniforms[1]) if len(shader.uniforms) > 1 else 0.0,
                float(shader.uniforms[2]) if len(shader.uniforms) > 2 else 0.0,
                0.0,
            )
            enc.setRenderPipelineState_(s.scene_pipeline_state)
            enc.setFragmentBytes_length_atIndex_(
                ctypes.byref(uniforms),
                ctypes.sizeof(uniforms),
                0,
            )
            enc.drawPrimitives_vertexStart_vertexCount_(
                _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP,
                0,
                4,
            )

        _draw_gpu_primitives(enc, s, frame)
        _draw_text_nodes(enc, s, frame)

        dynamic_overlay = _rasterize_overlay(frame, _is_dynamic_overlay_node)
        if dynamic_overlay is not None:
            s.dynamic_texture = _upload_overlay_texture(
                s.device,
                s.dynamic_texture,
                dynamic_overlay,
                width_attr="dynamic_texture_width",
                height_attr="dynamic_texture_height",
                state=s,
            )
            _draw_overlay_texture(enc, s, s.dynamic_texture)

        enc.endEncoding()
        cmd.presentDrawable_(drawable)
        cmd.commit()
        self._present_commits += 1

    def consume_telemetry(self) -> dict[str, int]:
        payload = {
            "next_drawable_nil": int(self._next_drawable_nil),
            "next_drawable_slow": int(self._next_drawable_slow),
            "present_commits": int(self._present_commits),
        }
        self._next_drawable_nil = 0
        self._next_drawable_slow = 0
        self._present_commits = 0
        return payload

    def shutdown(self, context: MetalContext) -> None:
        s = self._state
        if s is None:
            return
        s.window_system.destroy_window(s.window_handle)
        self._state = None

    def pump_events(self) -> None:
        s = self._state
        if s is not None:
            s.window_system.pump_events()

    def should_close(self) -> bool:
        s = self._state
        if s is None:
            return False
        return not s.window_system.is_window_open(s.window_handle)


@dataclass
class IOSMetalSceneTarget:
    width: int
    height: int
    backend: IOSMetalSceneBackend
    title: str = "Luvatrix App"
    _context: MetalContext | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    def start(self) -> None:
        if self._started:
            return
        self._context = self.backend.initialize(self.width, self.height, self.title)
        self._started = True

    def present_scene(self, frame: SceneFrame) -> None:
        if not self._started or self._context is None:
            raise RuntimeError("IOSMetalSceneTarget must be started before presenting scenes")
        self.backend.present_scene(self._context, frame)

    def stop(self) -> None:
        if not self._started:
            return
        assert self._context is not None
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


def _compile_scene_pipeline(device, layer) -> object:
    from rubicon.objc import ObjCClass

    lib = device.newLibraryWithSource_options_error_(_SCENE_MSL_SOURCE, None, None)
    if lib is None:
        raise RuntimeError("Metal scene shader compilation failed")
    vert_fn = lib.newFunctionWithName_("scene_vertex")
    frag_fn = lib.newFunctionWithName_("full_suite_fragment")
    if vert_fn is None or frag_fn is None:
        raise RuntimeError("Metal scene shader functions not found")
    desc = ObjCClass("MTLRenderPipelineDescriptor").alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    desc.colorAttachments.objectAtIndexedSubscript_(0).setPixelFormat_(layer.pixelFormat)
    pipeline = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline is None:
        raise RuntimeError("newRenderPipelineStateWithDescriptor returned nil for scene shader")
    return pipeline


def _compile_overlay_pipeline(device, layer) -> object:
    from rubicon.objc import ObjCClass

    lib = device.newLibraryWithSource_options_error_(_OVERLAY_MSL_SOURCE, None, None)
    if lib is None:
        raise RuntimeError("Metal overlay shader compilation failed")
    vert_fn = lib.newFunctionWithName_("overlay_vertex")
    frag_fn = lib.newFunctionWithName_("overlay_fragment")
    if vert_fn is None or frag_fn is None:
        raise RuntimeError("Metal overlay shader functions not found")
    desc = ObjCClass("MTLRenderPipelineDescriptor").alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    attach = desc.colorAttachments.objectAtIndexedSubscript_(0)
    attach.setPixelFormat_(layer.pixelFormat)
    attach.setBlendingEnabled_(True)
    attach.setRgbBlendOperation_(0)
    attach.setAlphaBlendOperation_(0)
    attach.setSourceRGBBlendFactor_(4)
    attach.setSourceAlphaBlendFactor_(1)
    attach.setDestinationRGBBlendFactor_(5)
    attach.setDestinationAlphaBlendFactor_(5)
    pipeline = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline is None:
        raise RuntimeError("newRenderPipelineStateWithDescriptor returned nil for overlay shader")
    return pipeline


def _compile_primitive_pipeline(device, layer) -> object:
    from rubicon.objc import ObjCClass

    lib = device.newLibraryWithSource_options_error_(_PRIMITIVE_MSL_SOURCE, None, None)
    if lib is None:
        raise RuntimeError("Metal primitive shader compilation failed")
    vert_fn = lib.newFunctionWithName_("primitive_vertex")
    frag_fn = lib.newFunctionWithName_("primitive_fragment")
    if vert_fn is None or frag_fn is None:
        raise RuntimeError("Metal primitive shader functions not found")
    desc = ObjCClass("MTLRenderPipelineDescriptor").alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    attach = desc.colorAttachments.objectAtIndexedSubscript_(0)
    attach.setPixelFormat_(layer.pixelFormat)
    attach.setBlendingEnabled_(True)
    attach.setRgbBlendOperation_(0)
    attach.setAlphaBlendOperation_(0)
    attach.setSourceRGBBlendFactor_(4)
    attach.setSourceAlphaBlendFactor_(1)
    attach.setDestinationRGBBlendFactor_(5)
    attach.setDestinationAlphaBlendFactor_(5)
    pipeline = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline is None:
        raise RuntimeError("newRenderPipelineStateWithDescriptor returned nil for primitive shader")
    return pipeline


def _compile_textured_quad_pipeline(device, layer) -> object:
    from rubicon.objc import ObjCClass

    lib = device.newLibraryWithSource_options_error_(_PRIMITIVE_MSL_SOURCE, None, None)
    if lib is None:
        raise RuntimeError("Metal textured quad shader compilation failed")
    vert_fn = lib.newFunctionWithName_("primitive_vertex")
    frag_fn = lib.newFunctionWithName_("textured_fragment")
    if vert_fn is None or frag_fn is None:
        raise RuntimeError("Metal textured quad shader functions not found")
    desc = ObjCClass("MTLRenderPipelineDescriptor").alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    attach = desc.colorAttachments.objectAtIndexedSubscript_(0)
    attach.setPixelFormat_(layer.pixelFormat)
    attach.setBlendingEnabled_(True)
    attach.setRgbBlendOperation_(0)
    attach.setAlphaBlendOperation_(0)
    attach.setSourceRGBBlendFactor_(4)
    attach.setSourceAlphaBlendFactor_(1)
    attach.setDestinationRGBBlendFactor_(5)
    attach.setDestinationAlphaBlendFactor_(5)
    pipeline = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline is None:
        raise RuntimeError("newRenderPipelineStateWithDescriptor returned nil for textured quad shader")
    return pipeline


def _first_background_shader(frame: SceneFrame) -> ShaderRectNode | None:
    for node in frame.nodes:
        if isinstance(node, ShaderRectNode) and node.shader == "full_suite_background":
            return node
    return None


def _draw_gpu_primitives(enc, state: _IOSMetalSceneState, frame: SceneFrame) -> None:
    primitives = [node for node in frame.nodes if isinstance(node, (RectNode, CircleNode))]
    if not primitives:
        return
    enc.setRenderPipelineState_(state.primitive_pipeline_state)
    for node in primitives:
        if isinstance(node, RectNode):
            quad = _QuadUniforms(
                float(node.x),
                float(node.y),
                float(node.width),
                float(node.height),
                float(frame.logical_width),
                float(frame.logical_height),
            )
            color = _rgba_floats(node.color_rgba)
            uniforms = _PrimitiveUniforms(*color, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        else:
            radius = float(node.radius)
            quad = _QuadUniforms(
                float(node.cx) - radius,
                float(node.cy) - radius,
                radius * 2.0,
                radius * 2.0,
                float(frame.logical_width),
                float(frame.logical_height),
            )
            color = _rgba_floats(node.fill_rgba)
            stroke = _rgba_floats(node.stroke_rgba)
            uniforms = _PrimitiveUniforms(
                *color,
                *stroke,
                float(node.stroke_width) / max(1.0, radius),
                1.0,
                0.0,
                0.0,
            )
        enc.setVertexBytes_length_atIndex_(
            ctypes.byref(quad),
            ctypes.sizeof(quad),
            0,
        )
        enc.setFragmentBytes_length_atIndex_(
            ctypes.byref(uniforms),
            ctypes.sizeof(uniforms),
            0,
        )
        enc.drawPrimitives_vertexStart_vertexCount_(
            _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP,
            0,
            4,
        )


def _draw_text_nodes(enc, state: _IOSMetalSceneState, frame: SceneFrame) -> None:
    scale = min(
        float(frame.display_width) / max(1.0, float(frame.logical_width)),
        float(frame.display_height) / max(1.0, float(frame.logical_height)),
    )
    text_nodes = [node for node in frame.nodes if isinstance(node, TextNode)]
    if not text_nodes:
        return
    enc.setRenderPipelineState_(state.textured_quad_pipeline_state)
    enc.setFragmentSamplerState_atIndex_(state.sampler_state, 0)
    for node in text_nodes:
        cached = _cached_text_texture(state, node, scale=scale)
        if cached is None:
            continue
        quad = _QuadUniforms(
            float(node.x),
            float(node.y),
            float(cached.width) / max(0.001, scale),
            float(cached.height) / max(0.001, scale),
            float(frame.logical_width),
            float(frame.logical_height),
        )
        enc.setVertexBytes_length_atIndex_(
            ctypes.byref(quad),
            ctypes.sizeof(quad),
            0,
        )
        enc.setFragmentTexture_atIndex_(cached.texture, 0)
        enc.drawPrimitives_vertexStart_vertexCount_(
            _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP,
            0,
            4,
        )


def _cached_text_texture(state: _IOSMetalSceneState, node: TextNode, *, scale: float) -> _CachedTextTexture | None:
    key = _text_node_texture_key(node, scale)
    cached = state.text_node_textures.get(key)
    if cached is not None:
        return cached
    rgba = _rasterize_text_node(node, scale=scale)
    if rgba is None:
        return None
    h, w, _ = rgba.shape
    texture = _create_texture(state.device, w, h)
    arr = accel.to_contiguous_numpy(rgba)
    texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
        _texture_region(texture, w, h),
        0,
        arr.ctypes.data_as(ctypes.c_void_p),
        w * 4,
    )
    cached = _CachedTextTexture(texture=texture, width=w, height=h)
    state.text_node_textures[key] = cached
    if len(state.text_node_textures) > 256:
        first_key = next(iter(state.text_node_textures))
        state.text_node_textures.pop(first_key, None)
    return cached


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
        mask = np.asarray(image, dtype=np.uint8)
    except Exception:
        width = max(1, int(round(len(node.text) * node.font_size_px * scale * 0.75)))
        height = max(1, int(round(node.font_size_px * scale * 1.25)))
        out = np.zeros((height, width, 4), dtype=np.uint8)
        _draw_text(out, TextNode(node.text, x=0, y=0, font_family=node.font_family, font_size_px=node.font_size_px, color_rgba=node.color_rgba), sx=scale, sy=scale)
        return out
    out = np.zeros((height, width, 4), dtype=np.uint8)
    color = np.asarray(node.color_rgba, dtype=np.uint8)
    out[:, :, 0] = color[0]
    out[:, :, 1] = color[1]
    out[:, :, 2] = color[2]
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
        round(float(scale), 3),
    )


def _rgba_floats(rgba: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    return (rgba[0] / 255.0, rgba[1] / 255.0, rgba[2] / 255.0, rgba[3] / 255.0)


def _rasterize_overlay(frame: SceneFrame, include_node) -> object | None:
    np = _numpy()
    if np is None:
        return None
    overlay = np.zeros((frame.display_height, frame.display_width, 4), dtype=np.uint8)
    sx = float(frame.display_width) / max(1.0, float(frame.logical_width))
    sy = float(frame.display_height) / max(1.0, float(frame.logical_height))
    touched = False
    for node in frame.nodes:
        if not include_node(node):
            continue
        if isinstance(node, (ClearNode, ShaderRectNode, SvgNode)):
            continue
        if isinstance(node, RectNode):
            if node.color_rgba[3] > 0:
                _draw_rect(overlay, node.x * sx, node.y * sy, node.width * sx, node.height * sy, node.color_rgba)
                touched = True
        elif isinstance(node, CircleNode):
            if node.fill_rgba[3] > 0 or node.stroke_rgba[3] > 0:
                _draw_circle(overlay, node, sx=sx, sy=sy)
                touched = True
        elif isinstance(node, TextNode):
            if node.text and node.color_rgba[3] > 0:
                _draw_text(overlay, node, sx=sx, sy=sy)
                touched = True
        elif isinstance(node, CpuLayerNode):
            _draw_layer(overlay, node, sx=sx, sy=sy)
            touched = True
        elif isinstance(node, ImageNode) and node.rgba is not None:
            _draw_layer(overlay, CpuLayerNode(node.x, node.y, node.width, node.height, node.rgba, node.z_index), sx=sx, sy=sy)
            touched = True
    return overlay if touched else None


def _is_static_text_node(node: object) -> bool:
    return False


def _is_dynamic_overlay_node(node: object) -> bool:
    return isinstance(node, (CpuLayerNode, ImageNode))


def _text_overlay_signature(frame: SceneFrame) -> tuple[object, ...]:
    items: list[object] = [frame.display_width, frame.display_height]
    for node in frame.nodes:
        if not _is_static_text_node(node):
            continue
        assert isinstance(node, TextNode)
        items.append(
            (
                node.text,
                round(float(node.x), 3),
                round(float(node.y), 3),
                node.font_family,
                round(float(node.font_size_px), 3),
                node.color_rgba,
                node.z_index,
                node.cache_key,
            )
        )
    return tuple(items) if len(items) > 2 else ()


def _upload_overlay_texture(device, texture, overlay, *, width_attr: str, height_attr: str, state: _IOSMetalSceneState):
    h, w, _ = overlay.shape
    if texture is None or getattr(state, width_attr) != w or getattr(state, height_attr) != h:
        texture = _create_texture(device, w, h)
        setattr(state, width_attr, w)
        setattr(state, height_attr, h)
    arr = accel.to_contiguous_numpy(overlay)
    texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
        _texture_region(texture, w, h),
        0,
        arr.ctypes.data_as(ctypes.c_void_p),
        w * 4,
    )
    return texture


def _draw_overlay_texture(enc, state: _IOSMetalSceneState, texture) -> None:
    enc.setRenderPipelineState_(state.overlay_pipeline_state)
    enc.setFragmentTexture_atIndex_(texture, 0)
    enc.setFragmentSamplerState_atIndex_(state.sampler_state, 0)
    enc.drawPrimitives_vertexStart_vertexCount_(
        _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP,
        0,
        4,
    )


def _texture_region(texture, width: int, height: int):
    # Ask rubicon for the exact anonymous struct type expected by
    # replaceRegion:mipmapLevel:withBytes:bytesPerRow: and fill it by layout.
    from luvatrix_core.platform.ios.metal_backend import _MTLOrigin, _MTLRegion, _MTLSize

    method = texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_
    return _coerce_struct(
        method,
        0,
        _MTLRegion(
            origin=_MTLOrigin(x=0, y=0, z=0),
            size=_MTLSize(width=width, height=height, depth=1),
        ),
    )
