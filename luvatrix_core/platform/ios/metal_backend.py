from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from dataclasses import dataclass, field

from luvatrix_core import accel
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

# ── Metal C function loader ────────────────────────────────────────────────────

_metal_cdll: ctypes.CDLL | None = None


def _metal_lib() -> ctypes.CDLL:
    global _metal_cdll
    if _metal_cdll is None:
        _metal_cdll = ctypes.CDLL("/System/Library/Frameworks/Metal.framework/Metal")
        _metal_cdll.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        _metal_cdll.MTLCreateSystemDefaultDevice.argtypes = []
    return _metal_cdll


# ── ObjC runtime loader + GIL-free nextDrawable ───────────────────────────────

_libobjc_cdll: ctypes.CDLL | None = None


def _libobjc_lib() -> ctypes.CDLL:
    global _libobjc_cdll
    if _libobjc_cdll is None:
        lib = ctypes.CDLL("/usr/lib/libobjc.dylib")
        lib.objc_msgSend.restype = ctypes.c_void_p
        lib.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.sel_registerName.restype = ctypes.c_void_p
        lib.sel_registerName.argtypes = [ctypes.c_char_p]
        _libobjc_cdll = lib
    return _libobjc_cdll


_sel_nextDrawable: int | None = None


def _next_drawable_gil_free(layer: object) -> object:
    """Call [layer nextDrawable] via ctypes so the Python GIL is released.

    rubicon-objc holds the GIL for every ObjC dispatch. When nextDrawable()
    blocks (e.g. allowsNextDrawableTimeout was reset by iOS), it stalls every
    Python thread, capping everything at ~12 fps. Routing through ctypes
    objc_msgSend releases the GIL for the duration of the call, so blocking
    nextDrawable() no longer affects the app loop or any other thread.
    """
    from rubicon.objc.api import ObjCInstance
    global _sel_nextDrawable
    lib = _libobjc_lib()
    if _sel_nextDrawable is None:
        _sel_nextDrawable = lib.sel_registerName(b"nextDrawable")
    raw = lib.objc_msgSend(layer._as_parameter_, _sel_nextDrawable)
    if not raw:
        return None
    return ObjCInstance(ctypes.c_void_p(raw))


def _ios_app_active() -> bool:
    try:
        from luvatrix_core.platform.ios.lifecycle import is_app_active

        return is_app_active()
    except Exception:  # noqa: BLE001
        return os.environ.get("LUVATRIX_IOS_APP_ACTIVE", "") != "0"


# ── Struct definitions (arm64/x86_64: NSUInteger = c_ulong = 8 bytes) ─────────

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
    """Reinterpret a ctypes struct as the _Anonymous type rubicon-objc built from the
    ObjC type encoding.  Both types have identical layouts; we just copy the bytes."""
    expected = bound_method.method.method_argtypes[arg_index]
    if isinstance(struct, expected):
        return struct
    return expected.from_buffer_copy(bytes(struct))


# ── Metal state ────────────────────────────────────────────────────────────────

@dataclass
class _MetalState:
    device: object
    command_queue: object
    pipeline_state: object
    sampler_state: object
    window_handle: object
    window_system: object
    src_texture: object = None
    src_texture_width: int = 0
    src_texture_height: int = 0


# ── Backend ────────────────────────────────────────────────────────────────────

@dataclass
class IOSMetalBackend:
    """
    Metal backend for iOS/iPadOS using rubicon-objc + ctypes.
    Does NOT use PyObjC — safe to import in the python-apple-support environment.
    """

    window_system: object = field(default=None)
    bar_color_rgba: tuple[int, int, int, int] = field(default=(0, 0, 0, 255))
    _state: _MetalState | None = field(default=None, init=False, repr=False)
    _was_inactive: bool = field(default=False, init=False, repr=False)
    _next_drawable_nil: int = field(default=0, init=False, repr=False)
    _next_drawable_slow: int = field(default=0, init=False, repr=False)
    _present_commits: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.window_system is None:
            from .window_system import UIKitWindowSystem
            self.window_system = UIKitWindowSystem()

    def initialize(self, width: int, height: int, title: str) -> MetalContext:
        from rubicon.objc.api import ObjCInstance

        window_handle = self.window_system.create_window(
            width, height, title, use_metal_layer=True, preserve_aspect_ratio=False
        )
        layer = window_handle.layer

        raw_ptr = _metal_lib().MTLCreateSystemDefaultDevice()
        if not raw_ptr:
            raise RuntimeError("MTLCreateSystemDefaultDevice returned nil — no Metal GPU")
        device = ObjCInstance(ctypes.c_void_p(raw_ptr))

        command_queue = device.newCommandQueue()
        if command_queue is None:
            raise RuntimeError("newCommandQueue returned nil")

        layer.setDevice_(device)
        layer.setPixelFormat_(_MTL_PIXEL_FORMAT_BGRA8_UNORM)
        layer.setFramebufferOnly_(False)
        # Return nil immediately instead of blocking the GIL if no drawable is ready
        # (e.g. after backgrounding/foregrounding). Without this, nextDrawable() can
        # stall for ~83ms after foreground restore, throttling the whole process to ~12fps.
        layer.setAllowsNextDrawableTimeout_(False)

        # drawableSize defaults to (0,0) until the compositor's first layout pass.
        # nextDrawable() returns nil when drawableSize is zero, so set it explicitly.
        set_size = layer.setDrawableSize_
        layer.setDrawableSize_(_coerce_struct(set_size, 0, _CGSize(float(width), float(height))))

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
        from rubicon.objc import ObjCClass

        s = self._state
        if s is None:
            raise RuntimeError("IOSMetalBackend is not initialized")

        app_active = _ios_app_active()
        if not app_active:
            self._was_inactive = True
            return
        if self._was_inactive:
            self._was_inactive = False
            try:
                s.window_handle.layer.setAllowsNextDrawableTimeout_(False)
                set_size = s.window_handle.layer.setDrawableSize_
                s.window_handle.layer.setDrawableSize_(
                    _coerce_struct(set_size, 0, _CGSize(float(context.width), float(context.height)))
                )
                print("[ios-metal] restored layer after foreground", file=sys.stderr, flush=True)
            except Exception as _exc:
                print(f"[ios-metal] restore failed: {_exc}", file=sys.stderr, flush=True)

        # Keep the source texture in RGBA order so presentation does not pay a
        # full-frame CPU channel-shuffle before every upload. The drawable is
        # still BGRA; Metal handles the render-target format conversion.
        h, w, _ = rgba.shape

        if s.src_texture is None or s.src_texture_width != w or s.src_texture_height != h:
            s.src_texture = _create_texture(s.device, w, h)
            s.src_texture_width = w
            s.src_texture_height = h

        arr = accel.to_contiguous_numpy(rgba)
        ptr = arr.ctypes.data_as(ctypes.c_void_p)

        # rubicon-objc builds its own _Anonymous ctypes struct types from ObjC type
        # encodings, and rejects foreign ctypes structs even with identical layout.
        # Read the expected type from the bound method's argtypes and copy bytes into it.
        region_raw = _MTLRegion(
            origin=_MTLOrigin(x=0, y=0, z=0),
            size=_MTLSize(width=w, height=h, depth=1),
        )
        replace_region = s.src_texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_
        region = _coerce_struct(replace_region, 0, region_raw)
        replace_region(region, 0, ptr, w * 4)

        t_pre = time.perf_counter()
        drawable = _next_drawable_gil_free(s.window_handle.layer)
        t_post = time.perf_counter()
        if drawable is None:
            self._next_drawable_nil += 1
            if t_post - t_pre > 0.010:
                self._next_drawable_slow += 1
                print(f"[ios-metal] nextDrawable blocked {(t_post - t_pre) * 1000:.0f}ms → nil", file=sys.stderr, flush=True)
            LOGGER.warning("nextDrawable=nil revision=%d", revision)
            return
        if t_post - t_pre > 0.010:
            self._next_drawable_slow += 1

        cmd = s.command_queue.commandBuffer()
        if cmd is None:
            LOGGER.warning("commandBuffer=nil revision=%d", revision)
            return

        # Letterbox/pillarbox: map native canvas into drawable preserving aspect ratio.
        native_h, native_w = h, w
        drawable_w, drawable_h = context.width, context.height
        scale = min(drawable_w / native_w, drawable_h / native_h)
        vp_w = native_w * scale
        vp_h = native_h * scale
        vp_x = (drawable_w - vp_w) / 2.0
        vp_y = (drawable_h - vp_h) / 2.0

        bar = self.bar_color_rgba
        pass_desc = ObjCClass("MTLRenderPassDescriptor").renderPassDescriptor()
        color_attach = pass_desc.colorAttachments.objectAtIndexedSubscript_(0)
        color_attach.setTexture_(drawable.texture)
        color_attach.setLoadAction_(_MTL_LOAD_ACTION_CLEAR)
        color_attach.setStoreAction_(_MTL_STORE_ACTION_STORE)
        set_clear = color_attach.setClearColor_
        color_attach.setClearColor_(
            _coerce_struct(set_clear, 0, _MTLClearColor(
                red=bar[0] / 255.0, green=bar[1] / 255.0,
                blue=bar[2] / 255.0, alpha=bar[3] / 255.0,
            ))
        )

        enc = cmd.renderCommandEncoderWithDescriptor_(pass_desc)
        enc.setRenderPipelineState_(s.pipeline_state)
        if vp_x > 0.5 or vp_y > 0.5:
            set_vp = enc.setViewport_
            enc.setViewport_(_coerce_struct(set_vp, 0, _MTLViewport(vp_x, vp_y, vp_w, vp_h, 0.0, 1.0)))
        enc.setFragmentTexture_atIndex_(s.src_texture, 0)
        enc.setFragmentSamplerState_atIndex_(s.sampler_state, 0)
        enc.drawPrimitives_vertexStart_vertexCount_(
            _MTL_PRIMITIVE_TYPE_TRIANGLE_STRIP, 0, 4
        )
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
        try:
            s.window_system.destroy_window(s.window_handle)
        except Exception:  # noqa: BLE001
            pass
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


# ── Helper functions (rubicon-objc versions) ───────────────────────────────────

def _compile_pipeline(device, layer) -> object:
    from rubicon.objc import ObjCClass

    # rubicon-objc returns the result directly (not a tuple like PyObjC)
    lib = device.newLibraryWithSource_options_error_(_MSL_SOURCE, None, None)
    if lib is None:
        raise RuntimeError("Metal shader compilation failed (newLibraryWithSource returned nil)")

    vert_fn = lib.newFunctionWithName_("vertex_main")
    frag_fn = lib.newFunctionWithName_("fragment_main")
    if vert_fn is None or frag_fn is None:
        raise RuntimeError("Metal shader functions not found after compilation")

    desc = ObjCClass("MTLRenderPipelineDescriptor").alloc().init()
    desc.setVertexFunction_(vert_fn)
    desc.setFragmentFunction_(frag_fn)
    desc.colorAttachments.objectAtIndexedSubscript_(0).setPixelFormat_(
        layer.pixelFormat
    )

    pipeline_state = device.newRenderPipelineStateWithDescriptor_error_(desc, None)
    if pipeline_state is None:
        raise RuntimeError("newRenderPipelineStateWithDescriptor returned nil")
    return pipeline_state


def _create_sampler(device) -> object:
    from rubicon.objc import ObjCClass

    desc = ObjCClass("MTLSamplerDescriptor").alloc().init()
    desc.setMinFilter_(_MTL_SAMPLER_MIN_MAG_FILTER_NEAREST)
    desc.setMagFilter_(_MTL_SAMPLER_MIN_MAG_FILTER_NEAREST)
    sampler = device.newSamplerStateWithDescriptor_(desc)
    if sampler is None:
        raise RuntimeError("newSamplerStateWithDescriptor returned nil")
    return sampler


def _create_texture(device, width: int, height: int) -> object:
    from rubicon.objc import ObjCClass

    desc = ObjCClass("MTLTextureDescriptor").texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
        _MTL_PIXEL_FORMAT_RGBA8_UNORM, width, height, False
    )
    desc.setUsage_(_MTL_TEXTURE_USAGE_SHADER_READ)
    desc.setStorageMode_(_MTL_RESOURCE_STORAGE_MODE_SHARED)
    texture = device.newTextureWithDescriptor_(desc)
    if texture is None:
        raise RuntimeError(f"newTextureWithDescriptor returned nil ({width}x{height})")
    return texture
