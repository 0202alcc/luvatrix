from __future__ import annotations

from dataclasses import dataclass, field

from luvatrix_core.core.scene_graph import CircleNode, ClearNode, RectNode, SceneFrame, ShaderRectNode, TextNode


OP_CLEAR = 1
OP_SHADER_RECT = 2
OP_RECT = 3
OP_CIRCLE = 4
OP_TEXT = 5

SHADER_IDS = {
    "solid": 1,
    "full_suite_background": 2,
}


@dataclass
class EncodedCommandBuffer:
    headers: list[int]
    floats: list[float]
    strings: list[str]
    width: int
    height: int


@dataclass
class CommandBufferBuilder:
    width: int
    height: int
    headers: list[int] = field(default_factory=list)
    floats: list[float] = field(default_factory=list)
    strings: list[str] = field(default_factory=list)
    _string_ids: dict[str, int] = field(default_factory=dict)

    def clear(self, color_rgba: tuple[int, int, int, int]) -> None:
        self.headers.extend([OP_CLEAR, len(self.floats), 4, 0])
        self.floats.extend(_rgba_floats(color_rgba))

    def shader_rect(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        shader: str,
        color_rgba: tuple[int, int, int, int] = (0, 0, 0, 255),
        uniforms: tuple[float, ...] = (),
    ) -> None:
        if shader not in SHADER_IDS:
            raise ValueError(f"unsupported web shader: {shader}")
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), *map(float, _rgba_floats(color_rgba)), *map(float, uniforms)]
        self.headers.extend([OP_SHADER_RECT, start, len(values), SHADER_IDS[shader]])
        self.floats.extend(values)

    def rect(self, *, x: float, y: float, width: float, height: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_RECT, start, len(values), 0])
        self.floats.extend(values)

    def circle(
        self,
        *,
        cx: float,
        cy: float,
        radius: float,
        fill_rgba: tuple[int, int, int, int],
        stroke_rgba: tuple[int, int, int, int] = (0, 0, 0, 0),
        stroke_width: float = 0.0,
    ) -> None:
        start = len(self.floats)
        values = [
            float(cx),
            float(cy),
            float(radius),
            *_rgba_floats(fill_rgba),
            *_rgba_floats(stroke_rgba),
            float(stroke_width),
        ]
        self.headers.extend([OP_CIRCLE, start, len(values), 0])
        self.floats.extend(values)

    def text(
        self,
        text: str,
        *,
        x: float,
        y: float,
        font_family: str = "Comic Mono",
        font_size_px: float = 14.0,
        color_rgba: tuple[int, int, int, int] = (255, 255, 255, 255),
        max_width_px: float | None = None,
    ) -> None:
        text_id = self._intern(text)
        font_id = self._intern(font_family)
        start = len(self.floats)
        values = [float(x), float(y), float(font_size_px), *_rgba_floats(color_rgba), float(max_width_px or 0.0)]
        self.headers.extend([OP_TEXT, start, len(values), text_id, font_id])
        self.floats.extend(values)

    def finish(self) -> EncodedCommandBuffer:
        return EncodedCommandBuffer(
            headers=list(self.headers),
            floats=list(self.floats),
            strings=list(self.strings),
            width=int(self.width),
            height=int(self.height),
        )

    def _intern(self, value: str) -> int:
        if value not in self._string_ids:
            self._string_ids[value] = len(self.strings)
            self.strings.append(value)
        return self._string_ids[value]


def encode_scene_frame(frame: SceneFrame) -> EncodedCommandBuffer:
    builder = CommandBufferBuilder(width=frame.logical_width, height=frame.logical_height)
    for node in frame.nodes:
        if isinstance(node, ClearNode):
            builder.clear(node.color_rgba)
        elif isinstance(node, ShaderRectNode):
            builder.shader_rect(
                x=node.x,
                y=node.y,
                width=node.width,
                height=node.height,
                shader=node.shader,
                color_rgba=node.color_rgba,
                uniforms=node.uniforms,
            )
        elif isinstance(node, RectNode):
            builder.rect(x=node.x, y=node.y, width=node.width, height=node.height, color_rgba=node.color_rgba)
        elif isinstance(node, CircleNode):
            builder.circle(
                cx=node.cx,
                cy=node.cy,
                radius=node.radius,
                fill_rgba=node.fill_rgba,
                stroke_rgba=node.stroke_rgba,
                stroke_width=node.stroke_width,
            )
        elif isinstance(node, TextNode):
            builder.text(
                node.text,
                x=node.x,
                y=node.y,
                font_family=node.font_family,
                font_size_px=node.font_size_px,
                color_rgba=node.color_rgba,
                max_width_px=node.max_width_px,
            )
    return builder.finish()


def _rgba_floats(color_rgba: tuple[int, int, int, int]) -> list[float]:
    return [max(0.0, min(1.0, float(ch) / 255.0)) for ch in color_rgba]
