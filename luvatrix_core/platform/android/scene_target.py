from __future__ import annotations

from dataclasses import dataclass, field
import json
import struct
import time

from luvatrix_core.core.scene_graph import (
    CircleNode,
    ClearNode,
    RectNode,
    SceneFrame,
    ShaderRectNode,
    TextNode,
)


@dataclass
class AndroidNativeSceneTarget:
    """Scene target that delegates retained scene drawing to the Android view."""

    presenter: object
    _started: bool = False
    frames_presented: int = 0
    last_revision: int | None = None
    _telemetry: dict[str, int] = field(default_factory=dict)
    _last_frame: SceneFrame | None = None

    def start(self) -> None:
        self._started = True

    def stop(self) -> None:
        self._started = False
        self._last_frame = None

    def pump_events(self) -> None:
        return

    def should_close(self) -> bool:
        return False

    def present_scene(self, frame: SceneFrame, target_present_time: float | None = None) -> None:
        _ = target_present_time
        if not self._started:
            raise RuntimeError("AndroidNativeSceneTarget.present_scene called before start")
        method = getattr(self.presenter, "presentScene", None) or getattr(self.presenter, "present_scene", None)
        binary_method = getattr(self.presenter, "presentSceneBinary", None) or getattr(
            self.presenter,
            "present_scene_binary",
            None,
        )
        if not callable(method) and not callable(binary_method):
            raise RuntimeError("Android native scene presenter must expose presentScene/present_scene")
        started = time.perf_counter_ns()
        transform_method = getattr(self.presenter, "presentSceneTransform", None) or getattr(
            self.presenter,
            "present_scene_transform",
            None,
        )
        transform_only = callable(transform_method) and _is_content_offset_only(self._last_frame, frame)
        if transform_only:
            encode_ns = 0
            transform_method(
                int(frame.revision),
                float(frame.content_offset_x),
                float(frame.content_offset_y),
            )
        else:
            if callable(binary_method):
                payload = _scene_packet(frame)
                binary_method(
                    payload,
                    int(frame.revision),
                    int(frame.logical_width),
                    int(frame.logical_height),
                    str(frame.presentation_mode or ""),
                )
            else:
                assert callable(method)
                payload = json.dumps(_scene_payload(frame), separators=(",", ":"))
                method(
                    payload,
                    int(frame.revision),
                    int(frame.logical_width),
                    int(frame.logical_height),
                    str(frame.presentation_mode or ""),
                )
            encode_ns = time.perf_counter_ns() - started
        present_ns = time.perf_counter_ns() - started
        self.frames_presented += 1
        self.last_revision = int(frame.revision)
        self._last_frame = frame
        self._telemetry.update(
            {
                "present_commits": int(self.frames_presented),
                "full_commits": int(self._telemetry.get("full_commits", 0)) + int(not transform_only),
                "transform_commits": int(self._telemetry.get("transform_commits", 0)) + int(transform_only),
                "last_enc_ms_x10": int(encode_ns / 100_000),
                "last_cmt_ms_x10": int(present_ns / 100_000),
            }
        )

    def consume_telemetry(self) -> dict[str, int]:
        return dict(self._telemetry)


def _scene_payload(frame: SceneFrame) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    out.append(
        {
            "type": "meta",
            "presentation_mode": frame.presentation_mode or "",
            "content_offset_x": float(frame.content_offset_x),
            "content_offset_y": float(frame.content_offset_y),
        }
    )
    for node in frame.nodes:
        if isinstance(node, ClearNode):
            out.append({"type": "clear", "color": list(node.color_rgba)})
        elif isinstance(node, ShaderRectNode):
            out.append(
                {
                    "type": "shader_rect",
                    "x": float(node.x),
                    "y": float(node.y),
                    "w": float(node.width),
                    "h": float(node.height),
                    "shader": str(node.shader),
                    "color": list(node.color_rgba),
                    "uniforms": [float(v) for v in node.uniforms],
                }
            )
        elif isinstance(node, RectNode):
            out.append(
                {
                    "type": "rect",
                    "x": float(node.x),
                    "y": float(node.y),
                    "w": float(node.width),
                    "h": float(node.height),
                    "color": list(node.color_rgba),
                }
            )
        elif isinstance(node, CircleNode):
            out.append(
                {
                    "type": "circle",
                    "cx": float(node.cx),
                    "cy": float(node.cy),
                    "r": float(node.radius),
                    "fill": list(node.fill_rgba),
                    "stroke": list(node.stroke_rgba),
                    "stroke_width": float(node.stroke_width),
                }
            )
        elif isinstance(node, TextNode):
            out.append(
                {
                    "type": "text",
                    "text": node.text,
                    "x": float(node.x),
                    "y": float(node.y),
                    "size": float(node.font_size_px),
                    "color": list(node.color_rgba),
                }
            )
    return out


def _scene_packet(frame: SceneFrame) -> bytes:
    """Encode native Android scene primitives without JSON or JNI UTF conversion.

    The packet starts with ``LVXS`` and version 1, followed by a counted sequence
    of primitive records.  It is intentionally little-endian and self-contained
    so the Kotlin fallback can defer decoding until native presentation fails.
    """

    records = [bytearray([1])]  # meta; offsets reside in the header.
    for node in frame.nodes:
        if isinstance(node, ClearNode):
            records.append(bytearray([2, *node.color_rgba]))
        elif isinstance(node, ShaderRectNode):
            shader = 1 if node.shader == "full_suite_background" else 0
            uniforms = tuple(float(value) for value in node.uniforms)
            record = bytearray([3])
            record.extend(struct.pack("<4dB4BH", node.x, node.y, node.width, node.height, shader, *node.color_rgba, len(uniforms)))
            if uniforms:
                record.extend(struct.pack(f"<{len(uniforms)}d", *uniforms))
            records.append(record)
        elif isinstance(node, RectNode):
            records.append(bytearray([4]) + struct.pack("<4d4B", node.x, node.y, node.width, node.height, *node.color_rgba))
        elif isinstance(node, CircleNode):
            records.append(
                bytearray([5])
                + struct.pack(
                    "<4d8B",
                    node.cx,
                    node.cy,
                    node.radius,
                    node.stroke_width,
                    *node.fill_rgba,
                    *node.stroke_rgba,
                )
            )
        elif isinstance(node, TextNode):
            text = node.text.encode("utf-8")
            if len(text) > 65535:
                continue
            records.append(
                bytearray([6])
                + struct.pack("<3d4BH", node.x, node.y, node.font_size_px, *node.color_rgba, len(text))
                + text
            )
    header = struct.pack(
        "<4sBHdd",
        b"LVXS",
        1,
        len(records),
        float(frame.content_offset_x),
        float(frame.content_offset_y),
    )
    return header + b"".join(records)


def _is_content_offset_only(previous: SceneFrame | None, incoming: SceneFrame) -> bool:
    if previous is None or not previous.retained or not incoming.retained:
        return False
    if (
        int(previous.logical_width) != int(incoming.logical_width)
        or int(previous.logical_height) != int(incoming.logical_height)
        or str(previous.presentation_mode or "") != str(incoming.presentation_mode or "")
    ):
        return False
    if (
        float(previous.content_offset_x) == float(incoming.content_offset_x)
        and float(previous.content_offset_y) == float(incoming.content_offset_y)
    ):
        return False
    if previous.nodes is incoming.nodes:
        return True
    try:
        equal = previous.nodes == incoming.nodes
        return equal if isinstance(equal, bool) else bool(equal)
    except (TypeError, ValueError, RuntimeError):
        return False
