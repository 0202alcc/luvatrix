from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass, field

from luvatrix_core import accel
from luvatrix_core.perf.copy_telemetry import add_copy_telemetry
from luvatrix_core.targets.metal_target import MetalContext

LOGGER = logging.getLogger(__name__)

# MTLPixelFormat
_MTL_PIXEL_FORMAT_RGBA8_UNORM = 70
_MTL_PIXEL_FORMAT_BGRA8_UNORM = 80

# MTLTextureUsage
_MTL_TEXTURE_USAGE_SHADER_READ = 1

# MTLResourceOptions (storage mode)
_MTL_RESOURCE_STORAGE_MODE_SHARED = 0

# MTLPrimitiveType
_MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP = 4

# MTLLoadAction / MTLStoreAction
_MTL_LOAD_ACTION_CLEAR = 2
_MTL_STORE_ACTION_STORE = 1

# MTLSamplerMinMagFilter
_MTL_SAMPLER_MIN_MAG_FILTER_NEAREST = 0

# ── Metal structs for PyObjC compatibility ────────────────────────────────────

class _MTLOrigin(ctypes.Structure):
    _fields_ = [("x", ctypes.c_ulong), ("y", ctypes.c_ulong), ("z", ctypes.c_ulong)]


class _MTLSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_ulong), ("height", ctypes.c_ulong), ("depth", ctypes.c_ulong)]


class _MTLRegion(ctypes.Structure):
    _fields_ = [("origin", _MTLOrigin), ("size", _MTLSize)]


class _MTLClearColor(ctypes.Structure):
    _fields_ = [
        ("red", ctypes.c_double),
        ("green", ctypes.c_double),
        ("blue", ctypes.c_double),
        ("alpha", ctypes.c_double),
    ]


class _MTLViewport(ctypes.Structure):
    _fields_ = [
        ("originX", ctypes.c_double),
        ("originY", ctypes.c_double),
        ("width", ctypes.c_double),
        ("height", ctypes.c_double),
        ("znear", ctypes.c_double),
        ("zfar", ctypes.c_double),
    ]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


def _coerce_struct(bound_method, arg_index: int, struct: ctypes.Structure) -> ctypes.Structure:
    expected = bound_method.method.method_argtypes[arg_index]
    if isinstance(struct, expected):
        return struct
    return expected.from_buffer_copy(bytes(struct))

# MTLTextureUsage
_MTL_TEXTURE_USAGE_SHADER_READ = 1

# MTLResourceOptions (storage mode)
_MTL_RESOURCE_STORAGE_MODE_SHARED = 0

# MTLPrimitiveType
_MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP = 4

# MTLLoadAction / MTLStoreAction
_MTL_LOAD_ACTION_CLEAR = 2
_MTL_STORE_ACTION_STORE = 1

# MTLSamplerMinMagFilter
_MTL_SAMPLER_MIN_MAG_FILTER_NEAREST = 0

_MSL_SOURCE = """
#include <metal_stdlib>
using namespace metal;

struct VertexOut {
    float4 position [[position]];
    float2 uv;
};

vertex VertexOut vertex_main(uint vid [[vertex_id]]) {
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

fragment float4 fragment_main(VertexOut in [[stage_in]],
                               texture2d<half> tex [[texture(0)]],
                               sampler smp [[sampler(0)]]) {
    return float4(tex.sample(smp, in.uv));
}
"""


@dataclass
class _MetalState:
    """Internal Metal objects held for the lifetime of an initialized backend."""

    device: object
    command_queue: object
    pipeline_state: object
    sampler_state: object
    window_handle: object
    window_system: object
    src_texture: object = None
    src_texture_width: int = 0
    src_texture_height: int = 0


@dataclass
class MacOSMetalBackend:
    window_system: object = field(default=None)
    bar_color_rgba: tuple[int, int, int, int] = field(default=(0, 0, 0, 255))
    resizable: bool = field(default=True)
    icon_path: str | None = field(default=None)
    _state: _MetalState | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.window_system is None:
            from .window_system import AppKitWindowSystem
            self.window_system = AppKitWindowSystem()

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
            raise RuntimeError("MTLCreateSystemDefaultDevice returned nil — no Metal GPU available")

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
        try:
            import Quartz  # type: ignore
            scale = float(window_handle.window.backingScaleFactor())
            layer.setContentsScale_(scale)
            if hasattr(layer, "setDrawableSize_"):
                layer.setDrawableSize_(Quartz.CGSizeMake(float(width) * scale, float(height) * scale))
        except Exception:
            pass

        pipeline_state = _compile_pipeline(device, layer)
        sampler_state = _create_sampler(device)

        self._state = _MetalState(
            device=device,
            command_queue=command_queue,
            pipeline_state=pipeline_state,
            sampler_state=sampler_state,
            window_handle=window_handle,
            window_system=self.window_system,
        )
        return MetalContext(width=width, height=height, title=title)

    def present(self, context: MetalContext, rgba, revision: int) -> None:
        import Metal

        s = self._state
        if s is None:
            raise RuntimeError("MacOSMetalBackend is not initialized")

        present_started = time.perf_counter_ns()

        # Keep the source texture in RGBA order so presentation does not pay a
        # full-frame CPU channel-shuffle before every upload. The drawable is
        # still BGRA; Metal handles the render-target format conversion.
        h, w, _ = rgba.shape

        # Ensure src_texture matches current frame dimensions
        if s.src_texture is None or s.src_texture_width != w or s.src_texture_height != h:
            s.src_texture = _create_texture(s.device, w, h)
            s.src_texture_width = w
            s.src_texture_height = h
            add_copy_telemetry(upload_image_realloc_count=1)

        arr, upload_bytes = _upload_buffer(rgba)
        replace_region = s.src_texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_
        region = ((0, 0, 0), (w, h, 1))

        try:
            scale = float(s.window_handle.window.backingScaleFactor())
            if hasattr(s.window_handle.layer, "setContentsScale_"):
                s.window_handle.layer.setContentsScale_(scale)
            if hasattr(s.window_handle.layer, "setDrawableSize_"):
                s.window_handle.layer.setDrawableSize_(_CGSize(float(context.width) * scale, float(context.height) * scale))
        except Exception:
            pass
        
        upload_started = time.perf_counter_ns()
        replace_region(region, 0, upload_bytes, w * 4)
        add_copy_telemetry(
            upload_bytes=w * h * 4,
            upload_memcpy_ns=time.perf_counter_ns() - upload_started,
        )

        drawable = s.window_handle.layer.nextDrawable()
        if drawable is None:
            LOGGER.warning("Metal: nextDrawable returned nil, skipping frame revision=%d", revision)
            return

        cmd = s.command_queue.commandBuffer()
        if cmd is None:
            LOGGER.warning("Metal: commandBuffer returned nil, skipping frame revision=%d", revision)
            return

        # Letterbox/pillarbox: map native canvas into drawable preserving aspect ratio.
        native_h, native_w = h, w
        texture = drawable.texture()
        try:
            drawable_w = float(texture.width())
            drawable_h = float(texture.height())
        except Exception:
            drawable_w = float(context.width)
            drawable_h = float(context.height)
        scale = min(drawable_w / native_w, drawable_h / native_h)
        vp_w = native_w * scale
        vp_h = native_h * scale
        vp_x = (drawable_w - vp_w) / 2.0
        vp_y = (drawable_h - vp_h) / 2.0

        bar = self.bar_color_rgba
        pass_desc = Metal.MTLRenderPassDescriptor.renderPassDescriptor()
        color_attach = pass_desc.colorAttachments().objectAtIndexedSubscript_(0)
        color_attach.setTexture_(drawable.texture())
        color_attach.setLoadAction_(_MTL_LOAD_ACTION_CLEAR)
        color_attach.setStoreAction_(_MTL_STORE_ACTION_STORE)
        color_attach.setClearColor_(Metal.MTLClearColorMake(
            bar[0] / 255.0, bar[1] / 255.0, bar[2] / 255.0, bar[3] / 255.0,
        ))

        enc = cmd.renderCommandEncoderWithDescriptor_(pass_desc)
        enc.setRenderPipelineState_(s.pipeline_state)
        enc.setViewport_((vp_x, vp_y, vp_w, vp_h, 0.0, 1.0))
        enc.setFragmentTexture_atIndex_(s.src_texture, 0)
        enc.setFragmentSamplerState_atIndex_(s.sampler_state, 0)
        enc.drawPrimitives_vertexStart_vertexCount_(
            _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP, 0, 4
        )
        enc.endEncoding()

        cmd.presentDrawable_(drawable)
        
        submit_started = time.perf_counter_ns()
        cmd.commit()
        add_copy_telemetry(
            queue_submit_ns=time.perf_counter_ns() - submit_started,
            queue_present_ns=time.perf_counter_ns() - present_started,
        )

    def shutdown(self, context: MetalContext) -> None:
        s = self._state
        if s is None:
            return
        try:
            s.window_system.destroy_window(s.window_handle)
        except Exception:  # noqa: BLE001
            pass
        self._state = None

    @property
    def _window_handle(self):
        s = self._state
        return s.window_handle if s is not None else None

    def pump_events(self) -> None:
        s = self._state
        if s is not None:
            s.window_system.pump_events()

    def should_close(self) -> bool:
        s = self._state
        if s is None:
            return True
        return not s.window_system.is_window_open(s.window_handle)


def _upload_buffer(rgba) -> tuple[object, object]:
    """Return a contiguous owner plus a buffer object usable by PyObjC."""
    if hasattr(rgba, "data_ptr") and callable(rgba.data_ptr) and hasattr(rgba, "contiguous"):
        owner = rgba.contiguous()
        if hasattr(owner, "numpy"):
            owner = owner.numpy()
        return owner, owner

    ctypes_view = getattr(rgba, "ctypes", None)
    if ctypes_view is not None and hasattr(ctypes_view, "data_as"):
        if not getattr(getattr(rgba, "flags", None), "c_contiguous", True):
            try:
                import numpy as np  # type: ignore
                rgba = np.ascontiguousarray(rgba)
                ctypes_view = rgba.ctypes
            except Exception:
                pass
        return rgba, rgba

    owner = accel.to_contiguous_numpy(rgba)
    return owner, owner


def _compile_pipeline(device, layer) -> object:
    import Metal

    lib, err = device.newLibraryWithSource_options_error_(_MSL_SOURCE, None, None)
    if lib is None:
        raise RuntimeError(f"Metal shader compilation failed: {err}")

    vert_fn = lib.newFunctionWithName_("vertex_main")
    frag_fn = lib.newFunctionWithName_("fragment_main")
    if vert_fn is None or frag_fn is None:
        raise RuntimeError("Metal shader functions not found after compilation")

    desc = Metal.MTLRenderPipelineDescriptor.alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    desc.colorAttachments().objectAtIndexedSubscript_(0).setPixelFormat_(
        layer.pixelFormat()
    )

    pipeline_state, err = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline_state is None:
        raise RuntimeError(f"failed to create MTLRenderPipelineState: {err}")
    return pipeline_state


def _create_sampler(device) -> object:
    import Metal

    desc = Metal.MTLSamplerDescriptor.alloc().init()
    desc.setMinFilter_(_MTL_SAMPLER_MIN_MAG_FILTER_NEAREST)
    desc.setMagFilter_(_MTL_SAMPLER_MIN_MAG_FILTER_NEAREST)
    sampler = device.newSamplerStateWithDescriptor_(desc)
    if sampler is None:
        raise RuntimeError("failed to create MTLSamplerState")
    return sampler


def _create_texture(device, width: int, height: int) -> object:
    import Metal

    desc = Metal.MTLTextureDescriptor.texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
        _MTL_PIXEL_FORMAT_RGBA8_UNORM, width, height, False
    )
    desc.setUsage_(_MTL_TEXTURE_USAGE_SHADER_READ)
    desc.setStorageMode_(_MTL_RESOURCE_STORAGE_MODE_SHARED)
    texture = device.newTextureWithDescriptor_(desc)
    if texture is None:
        raise RuntimeError(f"failed to create MTLTexture ({width}x{height})")
    return texture
