from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


Color = tuple[int, int, int, int]


@dataclass
class FrameBuffer:
    width: int
    height: int
    background: Color = (0, 0, 0, 255)

    def __post_init__(self) -> None:
        self.buffer = bytearray(self.width * self.height * 4)
        self.clear(self.background)

    def clear(self, color: Color | None = None) -> None:
        if color is None:
            color = self.background
        r, g, b, a = color
        buf = self.buffer
        for i in range(0, len(buf), 4):
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = a

    def to_bytes(self) -> bytes:
        return bytes(self.buffer)

    def draw_rect(self, x: int, y: int, w: int, h: int, color: Color) -> None:
        if w <= 0 or h <= 0:
            return
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        r, g, b, a = color
        buf = self.buffer
        if a >= 255:
            for yy in range(y0, y1):
                row = (yy * self.width + x0) * 4
                for _ in range(x0, x1):
                    buf[row] = r
                    buf[row + 1] = g
                    buf[row + 2] = b
                    buf[row + 3] = 255
                    row += 4
            return
        if a <= 0:
            return
        inv = 255 - a
        for yy in range(y0, y1):
            row = (yy * self.width + x0) * 4
            for _ in range(x0, x1):
                dr = buf[row]
                dg = buf[row + 1]
                db = buf[row + 2]
                buf[row] = (r * a + dr * inv) // 255
                buf[row + 1] = (g * a + dg * inv) // 255
                buf[row + 2] = (b * a + db * inv) // 255
                buf[row + 3] = 255
                row += 4

    def draw_circle(self, cx: int, cy: int, radius: int, color: Color) -> None:
        if radius <= 0:
            return
        r, g, b, a = color
        buf = self.buffer
        w = self.width
        h = self.height
        r2 = radius * radius
        y0 = max(0, cy - radius)
        y1 = min(h, cy + radius + 1)
        if a <= 0:
            return
        inv = 255 - a
        for yy in range(y0, y1):
            dy = yy - cy
            dy2 = dy * dy
            x_span = int((r2 - dy2) ** 0.5) if dy2 <= r2 else 0
            x0 = max(0, cx - x_span)
            x1 = min(w, cx + x_span + 1)
            row = (yy * w + x0) * 4
            if a >= 255:
                for _ in range(x0, x1):
                    buf[row] = r
                    buf[row + 1] = g
                    buf[row + 2] = b
                    buf[row + 3] = 255
                    row += 4
            else:
                for _ in range(x0, x1):
                    dr = buf[row]
                    dg = buf[row + 1]
                    db = buf[row + 2]
                    buf[row] = (r * a + dr * inv) // 255
                    buf[row + 1] = (g * a + dg * inv) // 255
                    buf[row + 2] = (b * a + db * inv) // 255
                    buf[row + 3] = 255
                    row += 4

    def draw_line(
        self, x0: int, y0: int, x1: int, y1: int, color: Color, thickness: int = 1
    ) -> None:
        if thickness <= 0:
            return
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        half = max(0, thickness // 2)
        while True:
            self.draw_rect(x0 - half, y0 - half, thickness, thickness, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def draw_polyline(
        self, points: Iterable[tuple[int, int]], color: Color, closed: bool = False
    ) -> None:
        pts = list(points)
        if len(pts) < 2:
            return
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            self.draw_line(x0, y0, x1, y1, color)
        if closed:
            x0, y0 = pts[-1]
            x1, y1 = pts[0]
            self.draw_line(x0, y0, x1, y1, color)
