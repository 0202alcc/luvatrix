"""
Backend-agnostic array primitives.

Tier 1 — torch:  macOS/Linux/Windows with GPU support (primary).
Tier 2 — numpy:  iOS embedded CPython with numpy wheel installed.
Tier 3 — pure:   iOS fallback when numpy is absent. Backed by bytearray.
                 Supports only the slice/indexing patterns used by luvatrix
                 internals and the hello_world example. matmul/transpose_2d
                 raise NotImplementedError (Multiply write-op is not used
                 on the pure-Python path).

Functions return the same concrete array type they receive. The selected
backend provides defaults such as zeros/from_sequence, while adapters may still
accept another known array type when that type is already available.
"""
from __future__ import annotations

import ctypes as _ctypes
import struct as _struct
import traceback as _traceback

# ── probe for available backends ──────────────────────────────────────────────
_torch = None
_np = None
BACKEND_IMPORT_ERROR: str | None = None


def _compact_import_error_part(value: str) -> str:
    value = " ".join(str(value).split())
    marker = "Original error was:"
    if marker in value:
        value = value.split(marker, 1)[1].strip()
    noisy = "IMPORTANT: PLEASE READ THIS FOR ADVICE ON HOW TO SOLVE THIS ISSUE!"
    if noisy in value:
        value = value.split(noisy, 1)[0].strip()
    source_tree = "you should not try to import numpy from its source directory"
    if source_tree in value:
        return value
    return value[:700]


try:
    import torch as _torch
except Exception as exc:
    BACKEND_IMPORT_ERROR = f"torch:{type(exc).__name__}:{exc}"

try:
    import numpy as _np
except Exception as exc:
    if _torch is None:
        cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
        parts: list[str] = []
        if cause is not None:
            parts.append(f"cause:{type(cause).__name__}:{cause}")
        parts.append(f"numpy:{type(exc).__name__}:{exc}")
        tb = "".join(_traceback.format_exception_only(type(exc), exc)).strip()
        if tb:
            parts.append(f"exc_only:{tb}")
        BACKEND_IMPORT_ERROR = " ".join(_compact_import_error_part(part) for part in parts)


# ── Tier 3: pure-Python array ─────────────────────────────────────────────────

class _CTypesView:
    """Minimal .ctypes shim so metal_backend can call .ctypes.data_as() uniformly."""

    def __init__(self, data: bytearray) -> None:
        self._data = data

    def data_as(self, typ):
        buf = (_ctypes.c_uint8 * len(self._data)).from_buffer(self._data)
        return _ctypes.cast(buf, typ)


class _PureArray:
    """
    Minimal uint8/float32 3-D array for the pure-Python backend.
    Only the operations actually called by luvatrix internals and hello_world
    are implemented; everything else raises NotImplementedError.
    """
    __slots__ = ("_data", "shape", "ndim", "dtype")

    def __init__(self, data: bytearray, shape: tuple[int, ...], dtype: str = "uint8") -> None:
        self._data = data
        self.shape = shape
        self.ndim = len(shape)
        self.dtype = dtype

    def copy(self) -> "_PureArray":
        return _PureArray(bytearray(self._data), self.shape, self.dtype)

    def reshape(self, shape: tuple[int, ...]) -> "_PureArray":
        return _PureArray(self._data, shape, self.dtype)

    @property
    def ctypes(self) -> _CTypesView:
        return _CTypesView(self._data)

    def astype(self, dtype: str) -> "_PureArray":
        if dtype == self.dtype:
            return self.copy()
        n_in = len(self._data) // (1 if self.dtype == "uint8" else 4)
        out = bytearray(n_in * (4 if dtype == "float32" else 1))
        if dtype == "float32" and self.dtype == "uint8":
            for i in range(n_in):
                _struct.pack_into("f", out, i * 4, float(self._data[i]))
        elif dtype == "uint8" and self.dtype == "float32":
            for i in range(n_in):
                v = _struct.unpack_from("f", self._data, i * 4)[0]
                out[i] = max(0, min(255, int(round(v))))
        return _PureArray(out, self.shape, dtype)

    def _norm(self, key):
        """Resolve a 3-element index tuple into (y0,y1,x0,x1,c_key)."""
        if not isinstance(key, tuple):
            key = (key,)
        if len(key) == 2:
            key = (*key, slice(None))
        H, W, C = self.shape

        def _sl(k, size):
            if isinstance(k, slice):
                s, e, st = k.indices(size)
                assert st == 1
                return s, e
            return int(k), int(k) + 1

        y0, y1 = _sl(key[0], H)
        x0, x1 = _sl(key[1], W)
        return y0, y1, x0, x1, key[2]

    def __getitem__(self, key):
        H, W, C = self.shape
        y0, y1, x0, x1, c_key = self._norm(key)

        # channel fancy index: x[:, :, [2, 1, 0, 3]]
        if isinstance(c_key, list):
            channels = c_key
            oh, ow, oc = y1 - y0, x1 - x0, len(channels)
            out = bytearray(oh * ow * oc)
            for yi in range(oh):
                for xi in range(ow):
                    src = ((y0 + yi) * W + (x0 + xi)) * C
                    dst = (yi * ow + xi) * oc
                    for ci, ch in enumerate(channels):
                        out[dst + ci] = self._data[src + ch]
            return _PureArray(out, (oh, ow, oc), self.dtype)

        # single channel: x[:, :, c]
        if isinstance(c_key, int):
            c = c_key
            oh, ow = y1 - y0, x1 - x0
            out = bytearray(oh * ow)
            for yi in range(oh):
                for xi in range(ow):
                    out[yi * ow + xi] = self._data[((y0 + yi) * W + (x0 + xi)) * C + c]
            return _PureArray(out, (oh, ow), self.dtype)

        # channel slice: x[y0:y1, x0:x1, :]
        if isinstance(c_key, slice):
            c0, c1, _ = c_key.indices(C)
            oc = c1 - c0
            oh, ow = y1 - y0, x1 - x0
            out = bytearray(oh * ow * oc)
            for yi in range(oh):
                for xi in range(ow):
                    src = ((y0 + yi) * W + (x0 + xi)) * C + c0
                    dst = (yi * ow + xi) * oc
                    out[dst:dst + oc] = self._data[src:src + oc]
            return _PureArray(out, (oh, ow, oc), self.dtype)

        raise IndexError(f"unsupported channel index: {c_key!r}")

    def __setitem__(self, key, value):
        H, W, C = self.shape

        # bool mask assignment: x[bool_mask] = array  (MAGENTA fill in sanitize)
        if isinstance(key, _PureArray) and key.dtype == "uint8" and key.ndim == 2:
            mask = key
            if isinstance(value, _PureArray):
                val_bytes = bytes(value._data[:C])
            else:
                val_bytes = bytes(int(v) & 0xFF for v in value)
            for yi in range(H):
                for xi in range(W):
                    if mask._data[yi * W + xi]:
                        base = (yi * W + xi) * C
                        self._data[base:base + C] = val_bytes
            return

        y0, y1, x0, x1, c_key = self._norm(key)

        # single channel scalar: x[:, :, c] = val
        if isinstance(c_key, int):
            c = c_key
            v = int(value) & 0xFF
            for yi in range(y0, y1):
                for xi in range(x0, x1):
                    self._data[((yi * W) + xi) * C + c] = v
            return

        # channel slice
        if isinstance(c_key, slice):
            c0, c1, _ = c_key.indices(C)
            oc = c1 - c0
            if isinstance(value, (tuple, list)):
                vals = bytes(int(v) & 0xFF for v in value)
                for yi in range(y0, y1):
                    for xi in range(x0, x1):
                        base = ((yi * W) + xi) * C + c0
                        self._data[base:base + oc] = vals
            elif isinstance(value, (int, float)):
                v = int(value) & 0xFF
                for yi in range(y0, y1):
                    for xi in range(x0, x1):
                        base = ((yi * W) + xi) * C + c0
                        for ci in range(oc):
                            self._data[base + ci] = v
            elif isinstance(value, _PureArray):
                src_H, src_W, src_C = value.shape
                for yi in range(y1 - y0):
                    for xi in range(x1 - x0):
                        src = (yi * src_W + xi) * src_C
                        dst = ((y0 + yi) * W + (x0 + xi)) * C + c0
                        self._data[dst:dst + oc] = value._data[src:src + min(src_C, oc)]
            else:
                raise TypeError(f"unsupported rhs type: {type(value)!r}")
            return

        raise IndexError(f"unsupported channel key in __setitem__: {c_key!r}")

    def sum(self) -> int:
        if self.dtype == "uint8":
            return sum(self._data)
        n = len(self._data) // 4
        return sum(_struct.unpack_from("f", self._data, i * 4)[0] for i in range(n))


def _shape_numel(shape: tuple[int, ...]) -> int:
    n = 1
    for size in shape:
        n *= int(size)
    return n


def _pure_item_size(x: _PureArray) -> int:
    if x.dtype == "uint8":
        return 1
    if x.dtype == "float32":
        return 4
    raise TypeError(f"unsupported pure array dtype for roll: {x.dtype!r}")


def _single_roll_shift(shifts) -> int:
    if isinstance(shifts, (tuple, list)):
        if len(shifts) != 1:
            raise ValueError("flat roll expects a single shift when dims is None")
        return int(shifts[0])
    return int(shifts)


def _normalize_roll_specs(shifts, dims, ndim: int) -> tuple[tuple[int, int], ...]:
    if isinstance(dims, int):
        axes = (dims,)
    elif isinstance(dims, (tuple, list)):
        axes = tuple(int(axis) for axis in dims)
    else:
        raise TypeError("dims must be an int, a tuple/list of ints, or None")
    if not axes:
        return ()
    if isinstance(shifts, (tuple, list)):
        shift_values = tuple(int(shift) for shift in shifts)
    else:
        shift_values = (int(shifts),) * len(axes)
    if len(shift_values) != len(axes):
        raise ValueError("shifts and dims must have the same length")

    specs: list[tuple[int, int]] = []
    for shift, axis in zip(shift_values, axes):
        if axis < 0:
            axis += ndim
        if axis < 0 or axis >= ndim:
            raise IndexError(f"roll axis {axis} out of range for array with {ndim} dimensions")
        specs.append((shift, axis))
    return tuple(specs)


def _roll_pure_flat(x: _PureArray, shift: int) -> _PureArray:
    total_items = _shape_numel(x.shape)
    if total_items <= 0:
        return x.copy()
    shift %= total_items
    if shift == 0:
        return x.copy()

    item_size = _pure_item_size(x)
    shift_bytes = shift * item_size
    out = x.copy()
    out._data[:shift_bytes] = x._data[-shift_bytes:]
    out._data[shift_bytes:] = x._data[:-shift_bytes]
    return out


def _roll_pure_axis(x: _PureArray, shift: int, axis: int) -> _PureArray:
    axis_size = int(x.shape[axis])
    if axis_size <= 0:
        return x.copy()
    shift %= axis_size
    if shift == 0:
        return x.copy()

    item_size = _pure_item_size(x)
    before = _shape_numel(x.shape[:axis])
    after = _shape_numel(x.shape[axis + 1 :])
    element_block_bytes = after * item_size
    axis_block_bytes = axis_size * element_block_bytes
    head_bytes = shift * element_block_bytes
    split = (axis_size - shift) * element_block_bytes
    out = x.copy()
    for prefix in range(before):
        base = prefix * axis_block_bytes
        end = base + axis_block_bytes
        out._data[base : base + head_bytes] = x._data[base + split : end]
        out._data[base + head_bytes : end] = x._data[base : base + split]
    return out


def blit(destination, source, *, x: int, y: int):
    """Copy a 3-D tile into a matrix in place, clipping at its boundaries."""
    if getattr(destination, "ndim", None) != 3 or getattr(source, "ndim", None) != 3:
        raise ValueError("blit expects 3-D destination and source arrays")

    destination_height, destination_width, destination_channels = (
        int(value) for value in destination.shape
    )
    source_height, source_width, source_channels = (int(value) for value in source.shape)
    if destination_channels != source_channels:
        raise ValueError(
            "blit source and destination must have the same channel count: "
            f"{source_channels} != {destination_channels}"
        )
    if getattr(destination, "dtype", None) != getattr(source, "dtype", None):
        raise ValueError("blit source and destination must have the same dtype")
    if source is destination:
        source = clone(source)

    x = int(x)
    y = int(y)
    destination_x0 = max(0, x)
    destination_y0 = max(0, y)
    destination_x1 = min(destination_width, x + source_width)
    destination_y1 = min(destination_height, y + source_height)
    if destination_x0 >= destination_x1 or destination_y0 >= destination_y1:
        return destination

    source_x0 = destination_x0 - x
    source_y0 = destination_y0 - y
    copy_width = destination_x1 - destination_x0
    copy_height = destination_y1 - destination_y0

    if isinstance(destination, _PureArray) and isinstance(source, _PureArray):
        item_size = _pure_item_size(destination)
        row_bytes = copy_width * destination_channels * item_size
        for row in range(copy_height):
            source_start = (
                ((source_y0 + row) * source_width + source_x0)
                * source_channels
                * item_size
            )
            destination_start = (
                ((destination_y0 + row) * destination_width + destination_x0)
                * destination_channels
                * item_size
            )
            destination._data[destination_start : destination_start + row_bytes] = source._data[
                source_start : source_start + row_bytes
            ]
        return destination

    destination[
        destination_y0:destination_y1,
        destination_x0:destination_x1,
        :,
    ] = source[
        source_y0 : source_y0 + copy_height,
        source_x0 : source_x0 + copy_width,
        :,
    ]
    return destination


# ── Tier 1: torch ─────────────────────────────────────────────────────────────

if _torch is not None:
    BACKEND: str = "torch"

    def zeros(shape: tuple[int, ...]):
        return _torch.zeros(shape, dtype=_torch.uint8)

    def from_sequence(values: list[int], shape: tuple[int, ...]):
        return _torch.tensor(values, dtype=_torch.uint8).reshape(shape)

    def clone(x):
        if _torch.is_tensor(x):
            return x.clone()
        if _np is not None and isinstance(x, _np.ndarray):
            return x.copy()
        return x.copy() if isinstance(x, _PureArray) else x

    def numel(x) -> int:
        if _torch.is_tensor(x):
            return int(x.numel())
        return int(x.size) if hasattr(x, "size") else sum(x.shape)

    def reshape(x, shape: tuple[int, ...]):
        return x.reshape(shape)

    def broadcast_to_clone(x, shape: tuple[int, ...]):
        return x.expand(shape).clone()

    def roll(x, shifts, dims=None):
        if _torch.is_tensor(x):
            return _torch.roll(x, shifts=shifts, dims=dims)
        if _np is not None and isinstance(x, _np.ndarray):
            return _np.roll(x, shift=shifts, axis=dims)
        if isinstance(x, _PureArray):
            if dims is None:
                return _roll_pure_flat(x, _single_roll_shift(shifts))
            out = x
            specs = _normalize_roll_specs(shifts, dims, x.ndim)
            if not specs:
                return x.copy()
            for shift, axis in specs:
                out = _roll_pure_axis(out, shift, axis)
            return out
        raise TypeError(f"roll expects a tensor, numpy array, or _PureArray, got {type(x)!r}")

    def isfinite(x):
        return _torch.isfinite(x)

    def all_finite(x) -> bool:
        return bool(_torch.isfinite(x).all())

    def any_over_last_dim(x):
        return _torch.any(x, dim=-1)

    def clamp(x, lo: float, hi: float):
        return _torch.clamp(x, lo, hi)

    def round_arr(x):
        return _torch.round(x)

    def matmul(a, b):
        return _torch.matmul(a, b)

    def transpose_2d(x):
        return x.transpose(0, 1)

    def to_float32(x):
        return x.to(_torch.float32)

    def to_uint8(x):
        return x.to(_torch.uint8)

    def is_array(x: object) -> bool:
        if _np is not None:
            return _torch.is_tensor(x) or isinstance(x, _np.ndarray)
        return _torch.is_tensor(x)

    def is_uint8(x: object) -> bool:
        if _torch.is_tensor(x):
            return x.dtype == _torch.uint8
        if _np is not None and isinstance(x, _np.ndarray):
            return x.dtype == _np.uint8
        return False

    def to_contiguous_numpy(x):
        if _torch.is_tensor(x):
            return x.contiguous().numpy()
        if _np is not None:
            return _np.ascontiguousarray(x)
        raise RuntimeError("numpy not available; cannot convert tensor to numpy")

    def coerce_float32(value, expected_shape: tuple[int, ...], label: str):
        if _np is not None and isinstance(value, _np.ndarray):
            if tuple(value.shape) != expected_shape:
                raise ValueError(f"{label} has invalid shape: {tuple(value.shape)} expected {expected_shape}")
            return _torch.from_numpy(value.astype(_np.float32))
        if not _torch.is_tensor(value):
            raise ValueError(f"{label} must be a torch.Tensor or numpy array, got {type(value)!r}")
        if tuple(value.shape) != expected_shape:
            raise ValueError(f"{label} has invalid shape: {tuple(value.shape)} expected {expected_shape}")
        if value.dtype == _torch.bool:
            return value.to(_torch.float32)
        if value.is_floating_point() or value.dtype in (
            _torch.int8, _torch.int16, _torch.int32, _torch.int64, _torch.uint8,
        ):
            return value.to(_torch.float32)
        raise ValueError(f"{label} must be a numeric tensor, got {value.dtype}")


# ── Tier 2: numpy ─────────────────────────────────────────────────────────────

elif _np is not None:
    BACKEND = "numpy"

    def zeros(shape: tuple[int, ...]):
        return _np.zeros(shape, dtype=_np.uint8)

    def from_sequence(values: list[int], shape: tuple[int, ...]):
        return _np.array(values, dtype=_np.uint8).reshape(shape)

    def clone(x):
        return x.copy()

    def numel(x) -> int:
        return int(x.size)

    def reshape(x, shape: tuple[int, ...]):
        return x.reshape(shape)

    def broadcast_to_clone(x, shape: tuple[int, ...]):
        return _np.broadcast_to(x, shape).copy()

    def roll(x, shifts, dims=None):
        return _np.roll(x, shift=shifts, axis=dims)

    def isfinite(x):
        return _np.isfinite(x)

    def all_finite(x) -> bool:
        return bool(_np.all(_np.isfinite(x)))

    def any_over_last_dim(x):
        return _np.any(x, axis=-1)

    def clamp(x, lo: float, hi: float):
        return _np.clip(x, lo, hi)

    def round_arr(x):
        return _np.round(x)

    def matmul(a, b):
        return _np.matmul(a, b)

    def transpose_2d(x):
        return x.T

    def to_float32(x):
        return x.astype(_np.float32)

    def to_uint8(x):
        return x.astype(_np.uint8)

    def is_array(x: object) -> bool:
        return isinstance(x, _np.ndarray)

    def is_uint8(x: object) -> bool:
        return isinstance(x, _np.ndarray) and x.dtype == _np.uint8

    def to_contiguous_numpy(x):
        return _np.ascontiguousarray(x)

    def coerce_float32(value, expected_shape: tuple[int, ...], label: str):
        if not isinstance(value, _np.ndarray):
            raise ValueError(f"{label} must be a numpy array, got {type(value)!r}")
        if tuple(value.shape) != expected_shape:
            raise ValueError(f"{label} has invalid shape: {tuple(value.shape)} expected {expected_shape}")
        return value.astype(_np.float32)


# ── Tier 3: pure Python ───────────────────────────────────────────────────────

else:
    BACKEND = "pure"

    def zeros(shape: tuple[int, ...]) -> _PureArray:
        n = 1
        for s in shape:
            n *= s
        return _PureArray(bytearray(n), shape, "uint8")

    def from_sequence(values: list[int], shape: tuple[int, ...]) -> _PureArray:
        n = 1
        for s in shape:
            n *= s
        data = bytearray(n)
        flat = [int(v) & 0xFF for v in values]
        for i in range(n):
            data[i] = flat[i % len(flat)]
        return _PureArray(data, shape, "uint8")

    def clone(x: _PureArray) -> _PureArray:
        return x.copy()

    def numel(x: _PureArray) -> int:
        n = 1
        for s in x.shape:
            n *= s
        return n

    def reshape(x: _PureArray, shape: tuple[int, ...]) -> _PureArray:
        return x.reshape(shape)

    def broadcast_to_clone(x: _PureArray, shape: tuple[int, ...]) -> _PureArray:
        H, W, C = shape
        src = bytes(x._data[:C])
        data = bytearray(H * W * C)
        for i in range(H * W):
            data[i * C:(i + 1) * C] = src
        return _PureArray(data, shape, x.dtype)

    def roll(x: _PureArray, shifts, dims=None) -> _PureArray:
        if dims is None:
            return _roll_pure_flat(x, _single_roll_shift(shifts))
        out = x
        specs = _normalize_roll_specs(shifts, dims, x.ndim)
        if not specs:
            return x.copy()
        for shift, axis in specs:
            out = _roll_pure_axis(out, shift, axis)
        return out

    def isfinite(x: _PureArray) -> _PureArray:
        # uint8 values are always finite — return all-True mask
        data = bytearray(len(x._data))
        for i in range(len(data)):
            data[i] = 1
        return _PureArray(data, x.shape, "uint8")

    def all_finite(x: _PureArray) -> bool:
        return True

    def any_over_last_dim(x: _PureArray) -> _PureArray:
        H, W, C = x.shape
        out = bytearray(H * W)
        for i in range(H * W):
            base = i * C
            out[i] = 1 if any(x._data[base + c] for c in range(C)) else 0
        return _PureArray(out, (H, W), "uint8")

    def clamp(x: _PureArray, lo: float, hi: float) -> _PureArray:
        assert x.dtype == "float32"
        data = bytearray(len(x._data))
        n = len(x._data) // 4
        for i in range(n):
            v = _struct.unpack_from("f", x._data, i * 4)[0]
            _struct.pack_into("f", data, i * 4, max(lo, min(hi, v)))
        return _PureArray(data, x.shape, "float32")

    def round_arr(x: _PureArray) -> _PureArray:
        assert x.dtype == "float32"
        data = bytearray(len(x._data))
        n = len(x._data) // 4
        for i in range(n):
            v = _struct.unpack_from("f", x._data, i * 4)[0]
            _struct.pack_into("f", data, i * 4, float(round(v)))
        return _PureArray(data, x.shape, "float32")

    def matmul(a, b):
        raise NotImplementedError("matmul not implemented in pure-Python backend (Multiply write-op is unsupported)")

    def transpose_2d(x):
        raise NotImplementedError("transpose_2d not implemented in pure-Python backend")

    def to_float32(x: _PureArray) -> _PureArray:
        return x.astype("float32")

    def to_uint8(x: _PureArray) -> _PureArray:
        return x.astype("uint8")

    def is_array(x: object) -> bool:
        return isinstance(x, _PureArray)

    def is_uint8(x: object) -> bool:
        return isinstance(x, _PureArray) and x.dtype == "uint8"

    def to_contiguous_numpy(x: _PureArray) -> _PureArray:
        # Returns _PureArray; .ctypes.data_as() works via _CTypesView.
        return x if isinstance(x, _PureArray) else clone(x)

    def coerce_float32(value, expected_shape: tuple[int, ...], label: str) -> _PureArray:
        if not isinstance(value, _PureArray):
            raise ValueError(f"{label} must be a _PureArray in pure-Python backend, got {type(value)!r}")
        if tuple(value.shape) != expected_shape:
            raise ValueError(f"{label} has invalid shape: {tuple(value.shape)} expected {expected_shape}")
        return value.astype("float32")
