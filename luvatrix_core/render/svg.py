from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import xml.etree.ElementTree as ET

from .framebuffer import Color, FrameBuffer


@dataclass(frozen=True)
class SvgRect:
    x: float
    y: float
    width: float
    height: float
    fill: Optional[Color]
    stroke: Optional[Color]
    stroke_width: float


@dataclass(frozen=True)
class SvgCircle:
    cx: float
    cy: float
    r: float
    fill: Optional[Color]
    stroke: Optional[Color]
    stroke_width: float


@dataclass(frozen=True)
class SvgLine:
    x1: float
    y1: float
    x2: float
    y2: float
    stroke: Optional[Color]
    stroke_width: float


@dataclass(frozen=True)
class SvgPolygon:
    points: list[tuple[float, float]]
    fill: Optional[Color]
    stroke: Optional[Color]
    stroke_width: float


@dataclass
class SvgDocument:
    width: float
    height: float
    viewbox: tuple[float, float, float, float]
    rects: list[SvgRect]
    circles: list[SvgCircle]
    lines: list[SvgLine]
    polygons: list[SvgPolygon]

    @classmethod
    def from_file(cls, path: Path) -> "SvgDocument":
        tree = ET.parse(path)
        root = tree.getroot()
        return cls._from_root(root)

    @classmethod
    def from_markup(cls, svg_markup: str) -> "SvgDocument":
        root = ET.fromstring(svg_markup)
        return cls._from_root(root)

    @classmethod
    def _from_root(cls, root: ET.Element) -> "SvgDocument":
        width = _parse_length(root.attrib.get("width"))
        height = _parse_length(root.attrib.get("height"))
        viewbox = _parse_viewbox(root.attrib.get("viewBox"))
        if viewbox is None:
            vb = (0.0, 0.0, width or 100.0, height or 100.0)
        else:
            vb = viewbox
        if width is None:
            width = vb[2]
        if height is None:
            height = vb[3]
        rects: list[SvgRect] = []
        circles: list[SvgCircle] = []
        lines: list[SvgLine] = []
        polygons: list[SvgPolygon] = []
        for elem in root.iter():
            tag = _strip_namespace(elem.tag)
            if tag == "rect":
                rects.append(_parse_rect(elem))
            elif tag == "circle":
                circles.append(_parse_circle(elem))
            elif tag == "line":
                line = _parse_line(elem)
                if line:
                    lines.append(line)
            elif tag == "polygon":
                poly = _parse_polygon(elem)
                if poly:
                    polygons.append(poly)
        return cls(
            width=width,
            height=height,
            viewbox=vb,
            rects=rects,
            circles=circles,
            lines=lines,
            polygons=polygons,
        )

    def render(
        self, fb: FrameBuffer, x: float, y: float, scale: float, opacity: float
    ) -> None:
        self.render_to_rect(
            fb,
            x=x,
            y=y,
            width=self.width * scale,
            height=self.height * scale,
            opacity=opacity,
        )

    def render_to_rect(
        self,
        fb: FrameBuffer,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        opacity: float,
    ) -> None:
        vb_x, vb_y, vb_w, vb_h = self.viewbox
        if width <= 0 or height <= 0:
            return
        scale_x = width / vb_w if vb_w else 1.0
        scale_y = height / vb_h if vb_h else 1.0
        for rect in self.rects:
            fill = _apply_opacity(rect.fill, opacity)
            stroke = _apply_opacity(rect.stroke, opacity)
            px = int(x + (rect.x - vb_x) * scale_x)
            py = int(y + (rect.y - vb_y) * scale_y)
            pw = int(rect.width * scale_x)
            ph = int(rect.height * scale_y)
            if fill:
                fb.draw_rect(px, py, pw, ph, fill)
            if stroke and rect.stroke_width > 0:
                sw = max(1, int(rect.stroke_width * ((abs(scale_x) + abs(scale_y)) / 2.0)))
                fb.draw_rect(px, py, pw, sw, stroke)
                fb.draw_rect(px, py + ph - sw, pw, sw, stroke)
                fb.draw_rect(px, py, sw, ph, stroke)
                fb.draw_rect(px + pw - sw, py, sw, ph, stroke)
        for circle in self.circles:
            fill = _apply_opacity(circle.fill, opacity)
            stroke = _apply_opacity(circle.stroke, opacity)
            px = int(x + (circle.cx - vb_x) * scale_x)
            py = int(y + (circle.cy - vb_y) * scale_y)
            pr = max(1, int(circle.r * ((abs(scale_x) + abs(scale_y)) / 2.0)))
            if fill:
                fb.draw_circle(px, py, pr, fill)
            if stroke and circle.stroke_width > 0:
                fb.draw_circle(px, py, pr, stroke)
        for line in self.lines:
            stroke = _apply_opacity(line.stroke, opacity)
            if not stroke:
                continue
            x0 = int(x + (line.x1 - vb_x) * scale_x)
            y0 = int(y + (line.y1 - vb_y) * scale_y)
            x1 = int(x + (line.x2 - vb_x) * scale_x)
            y1 = int(y + (line.y2 - vb_y) * scale_y)
            sw = max(1, int(line.stroke_width * ((abs(scale_x) + abs(scale_y)) / 2.0)))
            fb.draw_line(x0, y0, x1, y1, stroke, thickness=sw)
        for poly in self.polygons:
            fill = _apply_opacity(poly.fill, opacity)
            stroke = _apply_opacity(poly.stroke, opacity)
            pts = [
                (
                    int(x + (px - vb_x) * scale_x),
                    int(y + (py - vb_y) * scale_y),
                )
                for px, py in poly.points
            ]
            if fill:
                _fill_polygon(fb, pts, fill)
            if stroke:
                fb.draw_polyline(pts, stroke, closed=True)


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_length(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip()
    if value.endswith("px"):
        value = value[:-2]
    try:
        return float(value)
    except ValueError:
        return None


def _parse_viewbox(value: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    if not value:
        return None
    parts = value.replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _parse_rect(elem: ET.Element) -> SvgRect:
    x = _parse_length(elem.attrib.get("x")) or 0.0
    y = _parse_length(elem.attrib.get("y")) or 0.0
    w = _parse_length(elem.attrib.get("width")) or 0.0
    h = _parse_length(elem.attrib.get("height")) or 0.0
    fill = _parse_color(elem.attrib.get("fill"))
    stroke = _parse_color(elem.attrib.get("stroke"))
    stroke_width = _parse_length(elem.attrib.get("stroke-width")) or 0.0
    return SvgRect(x=x, y=y, width=w, height=h, fill=fill, stroke=stroke, stroke_width=stroke_width)


def _parse_circle(elem: ET.Element) -> SvgCircle:
    cx = _parse_length(elem.attrib.get("cx")) or 0.0
    cy = _parse_length(elem.attrib.get("cy")) or 0.0
    r = _parse_length(elem.attrib.get("r")) or 0.0
    fill = _parse_color(elem.attrib.get("fill"))
    stroke = _parse_color(elem.attrib.get("stroke"))
    stroke_width = _parse_length(elem.attrib.get("stroke-width")) or 0.0
    return SvgCircle(cx=cx, cy=cy, r=r, fill=fill, stroke=stroke, stroke_width=stroke_width)


def _parse_line(elem: ET.Element) -> Optional[SvgLine]:
    x1 = _parse_length(elem.attrib.get("x1"))
    y1 = _parse_length(elem.attrib.get("y1"))
    x2 = _parse_length(elem.attrib.get("x2"))
    y2 = _parse_length(elem.attrib.get("y2"))
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return None
    stroke = _parse_color(elem.attrib.get("stroke"))
    stroke_width = _parse_length(elem.attrib.get("stroke-width")) or 1.0
    return SvgLine(x1=x1, y1=y1, x2=x2, y2=y2, stroke=stroke, stroke_width=stroke_width)


def _parse_polygon(elem: ET.Element) -> Optional[SvgPolygon]:
    points = _parse_points(elem.attrib.get("points"))
    if not points:
        return None
    fill = _parse_color(elem.attrib.get("fill"))
    stroke = _parse_color(elem.attrib.get("stroke"))
    stroke_width = _parse_length(elem.attrib.get("stroke-width")) or 0.0
    return SvgPolygon(points=points, fill=fill, stroke=stroke, stroke_width=stroke_width)


def _parse_points(value: Optional[str]) -> list[tuple[float, float]]:
    if not value:
        return []
    parts = value.replace(",", " ").split()
    points: list[tuple[float, float]] = []
    it = iter(parts)
    for x_str, y_str in zip(it, it):
        try:
            points.append((float(x_str), float(y_str)))
        except ValueError:
            continue
    return points


def _parse_color(value: Optional[str]) -> Optional[Color]:
    if not value:
        return None
    value = value.strip()
    if value == "none":
        return None
    if value.startswith("#"):
        hex_value = value[1:]
        if len(hex_value) == 3:
            r = int(hex_value[0] * 2, 16)
            g = int(hex_value[1] * 2, 16)
            b = int(hex_value[2] * 2, 16)
            return (r, g, b, 255)
        if len(hex_value) == 4:
            r = int(hex_value[0] * 2, 16)
            g = int(hex_value[1] * 2, 16)
            b = int(hex_value[2] * 2, 16)
            a = int(hex_value[3] * 2, 16)
            return (r, g, b, a)
        if len(hex_value) == 6:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
            return (r, g, b, 255)
        if len(hex_value) == 8:
            r = int(hex_value[0:2], 16)
            g = int(hex_value[2:4], 16)
            b = int(hex_value[4:6], 16)
            a = int(hex_value[6:8], 16)
            return (r, g, b, a)
    if value.startswith("rgb"):
        numbers = value[value.find("(") + 1 : value.find(")")].split(",")
        if len(numbers) >= 3:
            try:
                r = int(numbers[0])
                g = int(numbers[1])
                b = int(numbers[2])
                return (r, g, b, 255)
            except ValueError:
                return None
    return None


def _apply_opacity(color: Optional[Color], opacity: float) -> Optional[Color]:
    if not color:
        return None
    if opacity >= 1.0:
        return color
    r, g, b, a = color
    return (r, g, b, max(0, min(255, int(a * opacity))))


def _fill_polygon(fb: FrameBuffer, points: Iterable[tuple[int, int]], color: Color) -> None:
    pts = list(points)
    if len(pts) < 3:
        return
    min_y = min(y for _, y in pts)
    max_y = max(y for _, y in pts)
    for y in range(min_y, max_y + 1):
        intersections: list[int] = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
            if y0 == y1:
                continue
            if (y >= min(y0, y1)) and (y < max(y0, y1)):
                x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                intersections.append(int(x))
        intersections.sort()
        for x0, x1 in zip(intersections[0::2], intersections[1::2]):
            fb.draw_rect(x0, y, x1 - x0 + 1, 1, color)
