from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw

_EPS = 1e-6


@dataclass(frozen=True)
class Affine:
    """2D affine map: x' = a*x + c*y + tx, y' = b*x + d*y + ty."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    @classmethod
    def identity(cls) -> "Affine":
        return cls()

    @classmethod
    def translate(cls, x: float, y: float) -> "Affine":
        return cls(tx=float(x), ty=float(y))

    @classmethod
    def scale(cls, sx: float, sy: float | None = None) -> "Affine":
        return cls(a=float(sx), d=float(sx if sy is None else sy))

    @classmethod
    def from_figma(cls, rows: Sequence[Sequence[float]]) -> "Affine":
        (a, c, tx), (b, d, ty) = rows[0], rows[1]
        return cls(float(a), float(b), float(c), float(d), float(tx), float(ty))

    def __matmul__(self, other: "Affine") -> "Affine":
        return Affine(
            a=self.a * other.a + self.c * other.b,
            b=self.b * other.a + self.d * other.b,
            c=self.a * other.c + self.c * other.d,
            d=self.b * other.c + self.d * other.d,
            tx=self.a * other.tx + self.c * other.ty + self.tx,
            ty=self.b * other.tx + self.d * other.ty + self.ty,
        )

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.c * y + self.tx, self.b * x + self.d * y + self.ty

    def apply_points(self, pts: np.ndarray) -> np.ndarray:
        out = np.empty_like(pts, dtype=np.float64)
        out[:, 0] = self.a * pts[:, 0] + self.c * pts[:, 1] + self.tx
        out[:, 1] = self.b * pts[:, 0] + self.d * pts[:, 1] + self.ty
        return out

    def inverse(self) -> "Affine":
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1e-12:
            return Affine(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        a, b, c, d = self.d / det, -self.b / det, -self.c / det, self.a / det
        return Affine(a, b, c, d, -(a * self.tx + c * self.ty), -(b * self.tx + d * self.ty))

    def bounds(self, x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
        pts = [self.apply(x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def is_axis_aligned(self) -> bool:
        return abs(self.b) < _EPS and abs(self.c) < _EPS and self.a > 0 and self.d > 0

    @property
    def mean_scale(self) -> float:
        return math.sqrt(abs(self.a * self.d - self.b * self.c)) or 1.0


@dataclass(frozen=True)
class Coverage:
    """Antialiased alpha mask covering device pixels [x0, x0+w) x [y0, y0+h)."""

    x0: int
    y0: int
    mask: np.ndarray

    @property
    def x1(self) -> int:
        return self.x0 + int(self.mask.shape[1])

    @property
    def y1(self) -> int:
        return self.y0 + int(self.mask.shape[0])


Rect = tuple[int, int, int, int]


def pixel_rect(bounds: tuple[float, float, float, float], clip: Rect, pad: float = 1.0) -> Rect | None:
    x0 = max(clip[0], int(math.floor(bounds[0] - pad)))
    y0 = max(clip[1], int(math.floor(bounds[1] - pad)))
    x1 = min(clip[2], int(math.ceil(bounds[2] + pad)))
    y1 = min(clip[3], int(math.ceil(bounds[3] + pad)))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def intersect(a: Rect, b: Rect) -> Rect | None:
    r = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return r if r[2] > r[0] and r[3] > r[1] else None


# ── SVG path data ─────────────────────────────────────────────────────────────

class PathError(ValueError):
    pass


_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

# A parsed subpath is a list of segments in absolute local coordinates:
# ("L", (x, y)), ("C", (x1, y1, x2, y2, x, y)), ("Q", (x1, y1, x, y)); the first
# entry is ("M", (x, y)).
Segment = tuple[str, tuple[float, ...]]


def parse_path(data: str) -> list[list[Segment]]:
    stripped = re.sub(r"[\s,]+", " ", data).strip()
    tokens = _TOKEN.findall(stripped)
    if re.sub(r"[\s]", "", "".join(tokens)) != re.sub(r"[\s,]", "", stripped):
        raise PathError(f"unsupported path data: {data[:40]!r}")
    subpaths: list[list[Segment]] = []
    current: list[Segment] = []
    x = y = sx = sy = 0.0
    last_ctrl: tuple[float, float] | None = None
    last_cmd = ""
    i = 0
    cmd = ""
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok
            i += 1
            if cmd in "Zz":
                if current:
                    current.append(("Z", ()))
                    subpaths.append(current)
                    current = []
                x, y = sx, sy
                last_cmd = "Z"
                continue
        elif not cmd:
            raise PathError("path data must start with a command")
        upper = cmd.upper()
        count = _ARGS[upper]
        args = tokens[i : i + count]
        if len(args) < count or any(t.isalpha() for t in args):
            raise PathError(f"command {cmd} expects {count} numbers")
        vals = [float(t) for t in args]
        i += count
        rel = cmd.islower()
        if upper == "M":
            if current:
                subpaths.append(current)
            x, y = (x + vals[0], y + vals[1]) if rel else (vals[0], vals[1])
            sx, sy = x, y
            current = [("M", (x, y))]
            cmd = "l" if rel else "L"
            last_ctrl = None
        else:
            if not current:
                current = [("M", (x, y))]
            if upper == "L":
                x, y = (x + vals[0], y + vals[1]) if rel else (vals[0], vals[1])
                current.append(("L", (x, y)))
                last_ctrl = None
            elif upper == "H":
                x = x + vals[0] if rel else vals[0]
                current.append(("L", (x, y)))
                last_ctrl = None
            elif upper == "V":
                y = y + vals[0] if rel else vals[0]
                current.append(("L", (x, y)))
                last_ctrl = None
            elif upper in "CS":
                if upper == "C":
                    pts = [(vals[k] + (x if rel else 0), vals[k + 1] + (y if rel else 0)) for k in (0, 2, 4)]
                else:
                    reflect = last_ctrl if last_cmd in "CcSs" and last_ctrl else (x, y)
                    c1 = (2 * x - reflect[0], 2 * y - reflect[1])
                    rest = [(vals[k] + (x if rel else 0), vals[k + 1] + (y if rel else 0)) for k in (0, 2)]
                    pts = [c1, *rest]
                current.append(("C", (*pts[0], *pts[1], *pts[2])))
                last_ctrl = pts[1]
                x, y = pts[2]
            elif upper in "QT":
                if upper == "Q":
                    pts = [(vals[k] + (x if rel else 0), vals[k + 1] + (y if rel else 0)) for k in (0, 2)]
                else:
                    reflect = last_ctrl if last_cmd in "QqTt" and last_ctrl else (x, y)
                    pts = [(2 * x - reflect[0], 2 * y - reflect[1]), (vals[0] + (x if rel else 0), vals[1] + (y if rel else 0))]
                current.append(("Q", (*pts[0], *pts[1])))
                last_ctrl = pts[0]
                x, y = pts[1]
            elif upper == "A":
                ex, ey = (x + vals[5], y + vals[6]) if rel else (vals[5], vals[6])
                for seg in _arc_to_cubics(x, y, vals[0], vals[1], vals[2], bool(vals[3]), bool(vals[4]), ex, ey):
                    current.append(seg)
                x, y = ex, ey
                last_ctrl = None
        last_cmd = cmd
    if current and len(current) > 1:
        subpaths.append(current)
    return subpaths


def _arc_to_cubics(
    x1: float, y1: float, rx: float, ry: float, phi_deg: float, large: bool, sweep: bool, x2: float, y2: float
) -> list[Segment]:
    if abs(rx) < _EPS or abs(ry) < _EPS:
        return [("L", (x2, y2))]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p**2) / (rx**2) + (y1p**2) / (ry**2)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx**2 * ry**2 - rx**2 * y1p**2 - ry**2 * x1p**2
    den = rx**2 * y1p**2 + ry**2 * x1p**2
    coef = math.sqrt(max(0.0, num / den)) if den > _EPS else 0.0
    if large == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(1, int(math.ceil(abs(dt) / (math.pi / 2))))
    step = dt / n
    k = 4 / 3 * math.tan(step / 4)
    segs: list[Segment] = []
    for i in range(n):
        a0, a1 = t1 + i * step, t1 + (i + 1) * step
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)
        p = [
            (c0 - k * s0, s0 + k * c0),
            (c1 + k * s1, s1 - k * c1),
            (c1, s1),
        ]
        out: list[float] = []
        for ux, uy in p:
            ux, uy = ux * rx, uy * ry
            out.extend((cp * ux - sp * uy + cx, sp * ux + cp * uy + cy))
        segs.append(("C", tuple(out)))
    return segs


def flatten(subpaths: list[list[Segment]], tf: Affine, *, tolerance_px: float = 0.25) -> list[np.ndarray]:
    """Flatten parsed subpaths into device-space polylines."""
    out: list[np.ndarray] = []
    for sub in subpaths:
        pts: list[tuple[float, float]] = []
        cur = (0.0, 0.0)
        for kind, vals in sub:
            if kind == "M":
                cur = (vals[0], vals[1])
                pts.append(tf.apply(*cur))
            elif kind == "L":
                cur = (vals[0], vals[1])
                pts.append(tf.apply(*cur))
            elif kind in {"C", "Q"}:
                ctrl = [cur] + [(vals[k], vals[k + 1]) for k in range(0, len(vals), 2)]
                dev = np.array([tf.apply(*p) for p in ctrl])
                length = float(np.sum(np.hypot(*np.diff(dev, axis=0).T)))
                n = int(min(256, max(4, math.sqrt(length / max(tolerance_px, 1e-3)) * 1.5)))
                t = np.linspace(0.0, 1.0, n + 1)[1:, None]
                if kind == "C":
                    p0, p1, p2, p3 = dev
                    curve = ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t * t * p2 + (t**3) * p3
                else:
                    p0, p1, p2 = dev
                    curve = ((1 - t) ** 2) * p0 + 2 * (1 - t) * t * p1 + t * t * p2
                pts.extend(map(tuple, curve))
                cur = ctrl[-1]
        if len(pts) >= 2:
            out.append(np.asarray(pts, dtype=np.float64))
    return out


def _signed_area(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _supersample(area: int) -> int:
    if area > 2_000_000:
        return 2
    if area > 500_000:
        return 3
    return 4


def polygon_coverage(polys: list[np.ndarray], rule: str, clip: Rect) -> Coverage | None:
    polys = [p for p in polys if len(p) >= 3]
    if not polys:
        return None
    allpts = np.concatenate(polys)
    rect = pixel_rect((allpts[:, 0].min(), allpts[:, 1].min(), allpts[:, 0].max(), allpts[:, 1].max()), clip)
    if rect is None:
        return None
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    ss = _supersample(w * h)
    acc = np.zeros((h * ss, w * ss), dtype=np.int16)
    for poly in polys:
        img = Image.new("L", (w * ss, h * ss), 0)
        pts = [((px - x0) * ss, (py - y0) * ss) for px, py in poly]
        ImageDraw.Draw(img).polygon(pts, fill=1)
        mask = np.asarray(img, dtype=np.int16)
        if rule == "EVENODD":
            acc ^= mask
        else:
            acc += mask if _signed_area(poly) >= 0 else -mask
    filled = (acc != 0).astype(np.float32)
    cov = filled.reshape(h, ss, w, ss).mean(axis=(1, 3))
    return Coverage(x0, y0, cov)


def polyline_coverage(polys: list[np.ndarray], width_px: float, clip: Rect) -> Coverage | None:
    polys = [p for p in polys if len(p) >= 2]
    if not polys:
        return None
    allpts = np.concatenate(polys)
    half = width_px / 2
    rect = pixel_rect(
        (allpts[:, 0].min() - half, allpts[:, 1].min() - half, allpts[:, 0].max() + half, allpts[:, 1].max() + half), clip
    )
    if rect is None:
        return None
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    ss = _supersample(w * h)
    img = Image.new("L", (w * ss, h * ss), 0)
    draw = ImageDraw.Draw(img)
    for poly in polys:
        pts = [((px - x0) * ss, (py - y0) * ss) for px, py in poly]
        draw.line(pts, fill=255, width=max(1, int(round(width_px * ss))), joint="curve")
    cov = (np.asarray(img, dtype=np.float32) / 255.0).reshape(h, ss, w, ss).mean(axis=(1, 3))
    return Coverage(x0, y0, cov)


# ── Primitive shapes ──────────────────────────────────────────────────────────

def _grid(rect: Rect) -> tuple[np.ndarray, np.ndarray]:
    x0, y0, x1, y1 = rect
    xs = np.arange(x0, x1, dtype=np.float32) + 0.5
    ys = np.arange(y0, y1, dtype=np.float32) + 0.5
    return np.meshgrid(xs, ys)


def _band(d: np.ndarray, lo: float, hi: float) -> np.ndarray:
    inner = np.clip(0.5 - (d - hi), 0.0, 1.0)
    if lo == -math.inf:
        return inner
    return inner - np.clip(0.5 - (d - lo), 0.0, 1.0)


class Shape:
    def polygons(self, tf: Affine) -> list[np.ndarray]:
        raise NotImplementedError

    def coverage(self, tf: Affine, clip: Rect, lo: float = -math.inf, hi: float = 0.0) -> Coverage | None:
        """Coverage of points whose signed distance to the outline lies in [lo, hi] device pixels."""
        if lo == -math.inf and abs(hi) < _EPS:
            return polygon_coverage(self.polygons(tf), "NONZERO", clip)
        outer = self._offset_polygons(tf, hi)
        cov = polygon_coverage(outer, "NONZERO", clip)
        if cov is None or lo == -math.inf:
            return cov
        inner = polygon_coverage(self._offset_polygons(tf, lo), "NONZERO", clip)
        if inner is None:
            return cov
        out = cov.mask.copy()
        ix0, iy0 = inner.x0 - cov.x0, inner.y0 - cov.y0
        region = out[iy0 : iy0 + inner.mask.shape[0], ix0 : ix0 + inner.mask.shape[1]]
        region -= inner.mask[: region.shape[0], : region.shape[1]]
        np.clip(out, 0.0, 1.0, out=out)
        return Coverage(cov.x0, cov.y0, out)

    def _offset_polygons(self, tf: Affine, offset_px: float) -> list[np.ndarray]:
        return self.polygons(tf)


class RoundedRect(Shape):
    def __init__(self, width: float, height: float, radii: Sequence[float] = (0, 0, 0, 0)) -> None:
        self.width = max(0.0, float(width))
        self.height = max(0.0, float(height))
        limit = min(self.width, self.height) / 2
        self.radii = tuple(max(0.0, min(limit, float(r))) for r in radii)  # tl, tr, br, bl

    def coverage(self, tf: Affine, clip: Rect, lo: float = -math.inf, hi: float = 0.0) -> Coverage | None:
        if not tf.is_axis_aligned:
            return super().coverage(tf, clip, lo, hi)
        x0, y0 = tf.apply(0.0, 0.0)
        x1, y1 = tf.apply(self.width, self.height)
        rect = pixel_rect((x0 - hi, y0 - hi, x1 + hi, y1 + hi), clip)
        if rect is None:
            return None
        px, py = _grid(rect)
        s = min(tf.a, tf.d)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hw, hh = (x1 - x0) / 2, (y1 - y0) / 2
        tl, tr, br, bl = (r * s for r in self.radii)
        r = np.where(px < cx, np.where(py < cy, tl, bl), np.where(py < cy, tr, br)).astype(np.float32)
        qx = np.abs(px - cx) - (hw - r)
        qy = np.abs(py - cy) - (hh - r)
        outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
        d = outside + np.minimum(np.maximum(qx, qy), 0.0) - r
        mask = _band(d, lo, hi).astype(np.float32)
        return Coverage(rect[0], rect[1], mask)

    def polygons(self, tf: Affine) -> list[np.ndarray]:
        return [tf.apply_points(self._local_outline(0.0))]

    def _offset_polygons(self, tf: Affine, offset_px: float) -> list[np.ndarray]:
        return [tf.apply_points(self._local_outline(offset_px / tf.mean_scale))]

    def _local_outline(self, offset: float) -> np.ndarray:
        w, h, o = self.width, self.height, offset
        tl, tr, br, bl = self.radii
        corners = (
            (tl, tl, tl, math.pi, -1, -1),
            (w - tr, tr, tr, 1.5 * math.pi, 1, -1),
            (w - br, h - br, br, 0.0, 1, 1),
            (bl, h - bl, bl, 0.5 * math.pi, -1, 1),
        )
        pts: list[tuple[float, float]] = []
        for cx, cy, r, start, sx, sy in corners:
            if r <= 0:
                pts.append((cx + sx * o, cy + sy * o))
                continue
            rr = max(0.0, r + o)
            steps = max(2, min(64, int(rr * 2)))
            for k in range(steps + 1):
                t = start + (math.pi / 2) * k / steps
                pts.append((cx + rr * math.cos(t), cy + rr * math.sin(t)))
        return np.asarray(pts, dtype=np.float64)


class Ellipse(Shape):
    def __init__(self, width: float, height: float) -> None:
        self.width = max(0.0, float(width))
        self.height = max(0.0, float(height))

    def coverage(self, tf: Affine, clip: Rect, lo: float = -math.inf, hi: float = 0.0) -> Coverage | None:
        if not tf.is_axis_aligned or self.width <= 0 or self.height <= 0:
            return super().coverage(tf, clip, lo, hi)
        x0, y0 = tf.apply(0.0, 0.0)
        x1, y1 = tf.apply(self.width, self.height)
        rect = pixel_rect((x0 - hi, y0 - hi, x1 + hi, y1 + hi), clip)
        if rect is None:
            return None
        px, py = _grid(rect)
        a, b = max((x1 - x0) / 2, _EPS), max((y1 - y0) / 2, _EPS)
        nx, ny = (px - (x0 + x1) / 2) / a, (py - (y0 + y1) / 2) / b
        k = np.sqrt(nx * nx + ny * ny)
        safe = np.maximum(k, 1e-4)
        grad = np.hypot(nx / (a * safe), ny / (b * safe))
        d = (k - 1.0) / np.maximum(grad, 1e-6)
        mask = _band(d, lo, hi).astype(np.float32)
        return Coverage(rect[0], rect[1], mask)

    def polygons(self, tf: Affine) -> list[np.ndarray]:
        return [tf.apply_points(self._local_outline(0.0, tf))]

    def _offset_polygons(self, tf: Affine, offset_px: float) -> list[np.ndarray]:
        return [tf.apply_points(self._local_outline(offset_px / tf.mean_scale, tf))]

    def _local_outline(self, offset: float, tf: Affine) -> np.ndarray:
        a, b = self.width / 2 + offset, self.height / 2 + offset
        n = int(min(512, max(24, (a + b) * tf.mean_scale)))
        t = np.linspace(0, 2 * math.pi, n, endpoint=False)
        return np.stack([self.width / 2 + a * np.cos(t), self.height / 2 + b * np.sin(t)], axis=1)


class PathShape(Shape):
    def __init__(self, paths: list[tuple[list[list[Segment]], str]]) -> None:
        self.paths = paths

    def polygons(self, tf: Affine) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for subpaths, _rule in self.paths:
            out.extend(flatten(subpaths, tf))
        return out

    def coverage(self, tf: Affine, clip: Rect, lo: float = -math.inf, hi: float = 0.0) -> Coverage | None:
        merged: Coverage | None = None
        for subpaths, rule in self.paths:
            cov = polygon_coverage(flatten(subpaths, tf), rule, clip)
            merged = union(merged, cov)
        return merged


def union(a: Coverage | None, b: Coverage | None) -> Coverage | None:
    if a is None:
        return b
    if b is None:
        return a
    x0, y0 = min(a.x0, b.x0), min(a.y0, b.y0)
    x1, y1 = max(a.x1, b.x1), max(a.y1, b.y1)
    out = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
    for cov in (a, b):
        region = out[cov.y0 - y0 : cov.y1 - y0, cov.x0 - x0 : cov.x1 - x0]
        np.maximum(region, cov.mask, out=region)
    return Coverage(x0, y0, out)


def path_shape_from_geometry(geometry: Sequence[dict]) -> PathShape | None:
    paths: list[tuple[list[list[Segment]], str]] = []
    for entry in geometry or ():
        data = (entry or {}).get("path")
        if not isinstance(data, str):
            continue
        try:
            parsed = parse_path(data)
        except PathError:
            continue
        if parsed:
            rule = str(entry.get("windingRule", "NONZERO")).upper()
            paths.append((parsed, "EVENODD" if rule == "EVENODD" else "NONZERO"))
    return PathShape(paths) if paths else None
