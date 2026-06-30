from __future__ import annotations

from dataclasses import dataclass, field

from luvatrix_core.core.scene_graph import Camera3DNode, CircleNode, ClearNode, Cube3DNode, Cuboid3DNode, DotGrid3DNode, DotPlane3DNode, GroundPlane3DNode, Horizon3DNode, Image3DNode, InfiniteDotPlane3DNode, InfiniteGrid3DNode, InfiniteGround3DNode, Line3DNode, Model3DNode, RectNode, RoundedCuboid3DNode, RoundedRectNode, SceneFrame, ShaderRectNode, Sphere3DNode, Text3DNode, TextNode


OP_CLEAR = 1
OP_SHADER_RECT = 2
OP_RECT = 3
OP_CIRCLE = 4
OP_TEXT = 5
OP_CAMERA_3D = 6
OP_CUBE_3D = 7
OP_DOT_GRID_3D = 8
OP_LINE_3D = 9
OP_HORIZON_3D = 10
OP_TEXT_3D = 11
OP_GROUND_PLANE_3D = 12
OP_DOT_PLANE_3D = 13
OP_INFINITE_GROUND_3D = 14
OP_INFINITE_DOT_PLANE_3D = 15
OP_CUBOID_3D = 16
OP_INFINITE_GRID_3D = 17
OP_SPHERE_3D = 18
OP_ROUNDED_RECT = 19
OP_MODEL_3D = 20
OP_ROUNDED_CUBOID_3D = 21
OP_IMAGE_3D = 22

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

    def rounded_rect(self, *, x: float, y: float, width: float, height: float, radius: float, color_rgba: tuple[int, int, int, int]) -> None:
        start = len(self.floats)
        values = [float(x), float(y), float(width), float(height), float(radius), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_ROUNDED_RECT, start, len(values), 0])
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
        rotation_deg: float = 0.0,
    ) -> None:
        text_id = self._intern(text)
        font_id = self._intern(font_family)
        start = len(self.floats)
        values = [float(x), float(y), float(font_size_px), *_rgba_floats(color_rgba), float(max_width_px or 0.0), float(rotation_deg)]
        self.headers.extend([OP_TEXT, start, len(values), text_id, font_id])
        self.floats.extend(values)

    def camera3d(
        self,
        *,
        position: tuple[float, float, float],
        target: tuple[float, float, float],
        up: tuple[float, float, float],
        fov_deg: float,
        near: float,
        far: float,
    ) -> None:
        start = len(self.floats)
        values = [*map(float, position), *map(float, target), *map(float, up), float(fov_deg), float(near), float(far)]
        self.headers.extend([OP_CAMERA_3D, start, len(values), 0])
        self.floats.extend(values)

    def cube3d(
        self,
        *,
        center: tuple[float, float, float],
        size: float,
        rotation: tuple[float, float, float],
        color_rgba: tuple[int, int, int, int],
        edge_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(size), *map(float, rotation), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_CUBE_3D, start, len(values), 0])
        self.floats.extend(values)

    def cuboid3d(
        self,
        *,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        rotation: tuple[float, float, float],
        color_rgba: tuple[int, int, int, int],
        edge_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), *map(float, size), *map(float, rotation), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_CUBOID_3D, start, len(values), 0])
        self.floats.extend(values)

    def rounded_cuboid3d(
        self,
        *,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        rotation: tuple[float, float, float],
        radius: float,
        color_rgba: tuple[int, int, int, int],
        edge_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), *map(float, size), *map(float, rotation), float(radius), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_ROUNDED_CUBOID_3D, start, len(values), 0])
        self.floats.extend(values)

    def sphere3d(
        self,
        *,
        center: tuple[float, float, float],
        radius: float,
        color_rgba: tuple[int, int, int, int],
        edge_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(radius), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_SPHERE_3D, start, len(values), 0])
        self.floats.extend(values)

    def model3d(
        self,
        *,
        asset: str,
        center: tuple[float, float, float],
        scale: tuple[float, float, float],
        rotation: tuple[float, float, float],
        color_rgba: tuple[int, int, int, int],
        edge_rgba: tuple[int, int, int, int],
    ) -> None:
        asset_id = self._intern(asset)
        start = len(self.floats)
        values = [*map(float, center), *map(float, scale), *map(float, rotation), *_rgba_floats(color_rgba), *_rgba_floats(edge_rgba)]
        self.headers.extend([OP_MODEL_3D, start, len(values), asset_id])
        self.floats.extend(values)

    def image3d(
        self,
        *,
        asset: str,
        center: tuple[float, float, float],
        size: tuple[float, float],
        rotation: tuple[float, float, float],
        opacity: float,
    ) -> None:
        asset_id = self._intern(asset)
        start = len(self.floats)
        values = [*map(float, center), *map(float, size), *map(float, rotation), float(opacity)]
        self.headers.extend([OP_IMAGE_3D, start, len(values), asset_id])
        self.floats.extend(values)

    def dot_grid3d(
        self,
        *,
        center: tuple[float, float, float],
        extent: float,
        spacing: float,
        point_size: float,
        color_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(extent), float(spacing), float(point_size), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_DOT_GRID_3D, start, len(values), 0])
        self.floats.extend(values)

    def line3d(
        self,
        *,
        start_point: tuple[float, float, float],
        end_point: tuple[float, float, float],
        color_rgba: tuple[int, int, int, int],
        width: float,
    ) -> None:
        start = len(self.floats)
        values = [*map(float, start_point), *map(float, end_point), *_rgba_floats(color_rgba), float(width)]
        self.headers.extend([OP_LINE_3D, start, len(values), 0])
        self.floats.extend(values)

    def dot_plane3d(
        self,
        *,
        center: tuple[float, float, float],
        width: float,
        depth: float,
        spacing: float,
        point_size: float,
        color_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(width), float(depth), float(spacing), float(point_size), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_DOT_PLANE_3D, start, len(values), 0])
        self.floats.extend(values)

    def ground_plane3d(
        self,
        *,
        center: tuple[float, float, float],
        width: float,
        depth: float,
        color_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [*map(float, center), float(width), float(depth), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_GROUND_PLANE_3D, start, len(values), 0])
        self.floats.extend(values)

    def infinite_ground3d(
        self,
        *,
        y: float,
        z_max: float,
        render_distance: float,
        color_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [float(y), float(z_max), float(render_distance), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_INFINITE_GROUND_3D, start, len(values), 0])
        self.floats.extend(values)

    def infinite_dot_plane3d(
        self,
        *,
        y: float,
        z_max: float,
        spacing: float,
        point_size: float,
        render_distance: float,
        color_rgba: tuple[int, int, int, int],
    ) -> None:
        start = len(self.floats)
        values = [float(y), float(z_max), float(spacing), float(point_size), float(render_distance), *_rgba_floats(color_rgba)]
        self.headers.extend([OP_INFINITE_DOT_PLANE_3D, start, len(values), 0])
        self.floats.extend(values)

    def infinite_grid3d(
        self,
        *,
        y: float,
        minor_spacing: float,
        major_spacing: float,
        render_distance: float,
        minor_rgba: tuple[int, int, int, int],
        major_rgba: tuple[int, int, int, int],
        minor_width: float,
        major_width: float,
    ) -> None:
        start = len(self.floats)
        values = [
            float(y),
            float(minor_spacing),
            float(major_spacing),
            float(render_distance),
            *_rgba_floats(minor_rgba),
            *_rgba_floats(major_rgba),
            float(minor_width),
            float(major_width),
        ]
        self.headers.extend([OP_INFINITE_GRID_3D, start, len(values), 0])
        self.floats.extend(values)

    def horizon3d(
        self,
        *,
        sky_rgba: tuple[int, int, int, int],
        ground_rgba: tuple[int, int, int, int],
        horizon_rgba: tuple[int, int, int, int],
        sky_horizon_rgba: tuple[int, int, int, int] | None,
        horizon_width: float,
    ) -> None:
        start = len(self.floats)
        sky_horizon = sky_rgba if sky_horizon_rgba is None else sky_horizon_rgba
        values = [*_rgba_floats(sky_rgba), *_rgba_floats(ground_rgba), *_rgba_floats(horizon_rgba), *_rgba_floats(sky_horizon), float(horizon_width)]
        self.headers.extend([OP_HORIZON_3D, start, len(values), 0])
        self.floats.extend(values)

    def text3d(
        self,
        text: str,
        *,
        position: tuple[float, float, float],
        height: float,
        depth: float,
        color_rgba: tuple[int, int, int, int],
        side_rgba: tuple[int, int, int, int],
        font_family: str,
    ) -> None:
        text_id = self._intern(text)
        font_id = self._intern(font_family)
        start = len(self.floats)
        values = [*map(float, position), float(height), float(depth), *_rgba_floats(color_rgba), *_rgba_floats(side_rgba)]
        self.headers.extend([OP_TEXT_3D, start, len(values), text_id, font_id])
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
        elif isinstance(node, RoundedRectNode):
            builder.rounded_rect(x=node.x, y=node.y, width=node.width, height=node.height, radius=node.radius, color_rgba=node.color_rgba)
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
                rotation_deg=node.rotation_deg,
            )
        elif isinstance(node, Camera3DNode):
            builder.camera3d(
                position=node.position,
                target=node.target,
                up=node.up,
                fov_deg=node.fov_deg,
                near=node.near,
                far=node.far,
            )
        elif isinstance(node, Cube3DNode):
            builder.cube3d(
                center=node.center,
                size=node.size,
                rotation=node.rotation,
                color_rgba=node.color_rgba,
                edge_rgba=node.edge_rgba,
            )
        elif isinstance(node, Cuboid3DNode):
            builder.cuboid3d(
                center=node.center,
                size=node.size,
                rotation=node.rotation,
                color_rgba=node.color_rgba,
                edge_rgba=node.edge_rgba,
            )
        elif isinstance(node, RoundedCuboid3DNode):
            builder.rounded_cuboid3d(
                center=node.center,
                size=node.size,
                rotation=node.rotation,
                radius=node.radius,
                color_rgba=node.color_rgba,
                edge_rgba=node.edge_rgba,
            )
        elif isinstance(node, Sphere3DNode):
            builder.sphere3d(
                center=node.center,
                radius=node.radius,
                color_rgba=node.color_rgba,
                edge_rgba=node.edge_rgba,
            )
        elif isinstance(node, Model3DNode):
            builder.model3d(
                asset=node.asset,
                center=node.center,
                scale=node.scale,
                rotation=node.rotation,
                color_rgba=node.color_rgba,
                edge_rgba=node.edge_rgba,
            )
        elif isinstance(node, Image3DNode):
            builder.image3d(
                asset=node.asset,
                center=node.center,
                size=node.size,
                rotation=node.rotation,
                opacity=node.opacity,
            )
        elif isinstance(node, DotGrid3DNode):
            builder.dot_grid3d(
                center=node.center,
                extent=node.extent,
                spacing=node.spacing,
                point_size=node.point_size,
                color_rgba=node.color_rgba,
            )
        elif isinstance(node, Line3DNode):
            builder.line3d(
                start_point=node.start,
                end_point=node.end,
                color_rgba=node.color_rgba,
                width=node.width,
            )
        elif isinstance(node, DotPlane3DNode):
            builder.dot_plane3d(
                center=node.center,
                width=node.width,
                depth=node.depth,
                spacing=node.spacing,
                point_size=node.point_size,
                color_rgba=node.color_rgba,
            )
        elif isinstance(node, GroundPlane3DNode):
            builder.ground_plane3d(
                center=node.center,
                width=node.width,
                depth=node.depth,
                color_rgba=node.color_rgba,
            )
        elif isinstance(node, InfiniteGround3DNode):
            builder.infinite_ground3d(
                y=node.y,
                z_max=node.z_max,
                render_distance=node.render_distance,
                color_rgba=node.color_rgba,
            )
        elif isinstance(node, InfiniteDotPlane3DNode):
            builder.infinite_dot_plane3d(
                y=node.y,
                z_max=node.z_max,
                spacing=node.spacing,
                point_size=node.point_size,
                render_distance=node.render_distance,
                color_rgba=node.color_rgba,
            )
        elif isinstance(node, InfiniteGrid3DNode):
            builder.infinite_grid3d(
                y=node.y,
                minor_spacing=node.minor_spacing,
                major_spacing=node.major_spacing,
                render_distance=node.render_distance,
                minor_rgba=node.minor_rgba,
                major_rgba=node.major_rgba,
                minor_width=node.minor_width,
                major_width=node.major_width,
            )
        elif isinstance(node, Horizon3DNode):
            builder.horizon3d(
                sky_rgba=node.sky_rgba,
                ground_rgba=node.ground_rgba,
                horizon_rgba=node.horizon_rgba,
                sky_horizon_rgba=node.sky_horizon_rgba,
                horizon_width=node.horizon_width,
            )
        elif isinstance(node, Text3DNode):
            builder.text3d(
                node.text,
                position=node.position,
                height=node.height,
                depth=node.depth,
                color_rgba=node.color_rgba,
                side_rgba=node.side_rgba,
                font_family=node.font_family,
            )
    return builder.finish()


def _rgba_floats(color_rgba: tuple[int, int, int, int]) -> list[float]:
    return [max(0.0, min(1.0, float(ch) / 255.0)) for ch in color_rgba]
