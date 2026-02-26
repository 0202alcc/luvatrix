from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


PRESET_SCREEN_TL = "screen_tl"
PRESET_CARTESIAN_BL = "cartesian_bl"
PRESET_CARTESIAN_CENTER = "cartesian_center"


@dataclass(frozen=True)
class CoordinateFrame:
    name: str
    origin: tuple[float, float]
    basis_x: tuple[float, float]
    basis_y: tuple[float, float]

    def determinant(self) -> float:
        exx, exy = self.basis_x
        eyx, eyy = self.basis_y
        return (exx * eyy) - (exy * eyx)


class CoordinateFrameRegistry:
    """Manages coordinate frame definitions and transforms for one viewport."""

    def __init__(self, width: int, height: int, default_frame: str = PRESET_SCREEN_TL) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be > 0")
        self._width = width
        self._height = height
        self._custom_frames: dict[str, CoordinateFrame] = {}
        self._default_frame = default_frame
        self._resolve(default_frame)

    @property
    def default_frame(self) -> str:
        return self._default_frame

    def set_default_frame(self, frame_name: str) -> None:
        self._resolve(frame_name)
        self._default_frame = frame_name

    def define_frame(
        self,
        name: str,
        origin: tuple[float, float],
        basis_x: tuple[float, float],
        basis_y: tuple[float, float],
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("frame name must be a non-empty string")
        if name in _PRESET_NAMES:
            raise ValueError(f"`{name}` is reserved as a preset frame name")
        frame = CoordinateFrame(name=name, origin=origin, basis_x=basis_x, basis_y=basis_y)
        if abs(frame.determinant()) < 1e-9:
            raise ValueError(f"frame `{name}` basis vectors are singular")
        self._custom_frames[name] = frame

    def list_frames(self) -> list[str]:
        names = list(_PRESET_NAMES) + sorted(self._custom_frames.keys())
        return names

    def transform_point(
        self,
        point: tuple[float, float],
        from_frame: str | None = None,
        to_frame: str | None = None,
    ) -> tuple[float, float]:
        src = self._resolve(from_frame or self._default_frame)
        dst = self._resolve(to_frame or self._default_frame)
        cx, cy = _to_canonical(point, src)
        return _from_canonical((cx, cy), dst)

    def transform_vector(
        self,
        vector: tuple[float, float],
        from_frame: str | None = None,
        to_frame: str | None = None,
    ) -> tuple[float, float]:
        src = self._resolve(from_frame or self._default_frame)
        dst = self._resolve(to_frame or self._default_frame)
        vx, vy = _to_canonical_vector(vector, src)
        return _from_canonical_vector((vx, vy), dst)

    def to_render_coords(self, point: tuple[float, float], frame: str | None = None) -> tuple[float, float]:
        return self.transform_point(point, from_frame=frame, to_frame=PRESET_SCREEN_TL)

    def from_render_coords(self, point: tuple[float, float], frame: str | None = None) -> tuple[float, float]:
        return self.transform_point(point, from_frame=PRESET_SCREEN_TL, to_frame=frame)

    def _resolve(self, frame_name: str) -> CoordinateFrame:
        if frame_name in self._custom_frames:
            return self._custom_frames[frame_name]
        return _preset_frame(frame_name, self._width, self._height)


_PRESET_NAMES = {PRESET_SCREEN_TL, PRESET_CARTESIAN_BL, PRESET_CARTESIAN_CENTER}


def _preset_frame(name: str, width: int, height: int) -> CoordinateFrame:
    if name == PRESET_SCREEN_TL:
        return CoordinateFrame(
            name=name,
            origin=(0.0, 0.0),
            basis_x=(1.0, 0.0),
            basis_y=(0.0, 1.0),
        )
    if name == PRESET_CARTESIAN_BL:
        return CoordinateFrame(
            name=name,
            origin=(0.0, float(height - 1)),
            basis_x=(1.0, 0.0),
            basis_y=(0.0, -1.0),
        )
    if name == PRESET_CARTESIAN_CENTER:
        return CoordinateFrame(
            name=name,
            origin=((float(width) - 1.0) / 2.0, (float(height) - 1.0) / 2.0),
            basis_x=(1.0, 0.0),
            basis_y=(0.0, -1.0),
        )
    raise ValueError(f"unknown coordinate frame: {name}")


def _to_canonical(point: tuple[float, float], frame: CoordinateFrame) -> tuple[float, float]:
    x, y = point
    ox, oy = frame.origin
    exx, exy = frame.basis_x
    eyx, eyy = frame.basis_y
    return (ox + x * exx + y * eyx, oy + x * exy + y * eyy)


def _from_canonical(point: tuple[float, float], frame: CoordinateFrame) -> tuple[float, float]:
    px, py = point
    ox, oy = frame.origin
    exx, exy = frame.basis_x
    eyx, eyy = frame.basis_y
    det = frame.determinant()
    if abs(det) < 1e-9:
        raise ValueError(f"frame `{frame.name}` basis vectors are singular")
    dx = px - ox
    dy = py - oy
    x = ((dx * eyy) - (dy * eyx)) / det
    y = (-(dx * exy) + (dy * exx)) / det
    return (x, y)


def _to_canonical_vector(vector: tuple[float, float], frame: CoordinateFrame) -> tuple[float, float]:
    vx, vy = vector
    exx, exy = frame.basis_x
    eyx, eyy = frame.basis_y
    return (vx * exx + vy * eyx, vx * exy + vy * eyy)


def _from_canonical_vector(vector: tuple[float, float], frame: CoordinateFrame) -> tuple[float, float]:
    vx, vy = vector
    exx, exy = frame.basis_x
    eyx, eyy = frame.basis_y
    det = frame.determinant()
    if abs(det) < 1e-9:
        raise ValueError(f"frame `{frame.name}` basis vectors are singular")
    x = ((vx * eyy) - (vy * eyx)) / det
    y = (-(vx * exy) + (vy * exx)) / det
    return (x, y)
