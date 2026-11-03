from __future__ import annotations

from typing import Any


def solid(r: float, g: float, b: float, a: float = 1.0, *, opacity: float | None = None) -> dict[str, Any]:
    paint: dict[str, Any] = {"type": "SOLID", "color": {"r": r, "g": g, "b": b, "a": a}}
    if opacity is not None:
        paint["opacity"] = opacity
    return paint


def box(x: float, y: float, w: float, h: float) -> dict[str, float]:
    return {"x": float(x), "y": float(y), "width": float(w), "height": float(h)}


def node(
    node_id: str,
    node_type: str,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": node_id,
        "type": node_type,
        "name": name,
        "absoluteBoundingBox": box(x, y, w, h),
    }
    out.update(extra)
    return out


def navigate(destination_id: str) -> list[dict[str, Any]]:
    return [
        {
            "trigger": {"type": "ON_CLICK"},
            "actions": [
                {
                    "type": "NODE",
                    "destinationId": destination_id,
                    "navigation": "NAVIGATE",
                    "transition": None,
                }
            ],
        }
    ]


def back() -> list[dict[str, Any]]:
    return [{"trigger": {"type": "ON_CLICK"}, "actions": [{"type": "BACK"}]}]


def two_screen_file() -> dict[str, Any]:
    """A Figma REST `GET /v1/files/:key` payload with two prototype screens.

    The canvas places Home at x=1000 so frame-relative positioning is exercised.
    """
    home = node(
        "1:1",
        "FRAME",
        "Home",
        1000,
        0,
        100,
        200,
        fills=[solid(1, 1, 1)],
        clipsContent=True,
        children=[
            node(
                "1:2",
                "RECTANGLE",
                "Go Button",
                1010,
                150,
                80,
                30,
                fills=[solid(1, 0, 0)],
                cornerRadius=8,
                interactions=navigate("2:1"),
            ),
            node(
                "1:3",
                "RECTANGLE",
                "Hidden",
                1000,
                0,
                100,
                200,
                visible=False,
                fills=[solid(0, 0, 0)],
            ),
        ],
    )
    detail = node(
        "2:1",
        "FRAME",
        "Detail",
        1200,
        0,
        100,
        200,
        fills=[solid(0, 0, 1)],
        children=[
            node(
                "2:2",
                "RECTANGLE",
                "Back",
                1200,
                0,
                40,
                40,
                fills=[solid(0, 1, 0)],
                interactions=back(),
            ),
            node(
                "2:3",
                "FRAME",
                "Legacy Link",
                1250,
                100,
                40,
                40,
                fills=[solid(1, 1, 0)],
                transitionNodeID="1:1",
            ),
        ],
    )
    return {
        "name": "Two Screens",
        "schemaVersion": 0,
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "name": "Document",
            "children": [
                {
                    "id": "0:1",
                    "type": "CANVAS",
                    "name": "Page 1",
                    "backgroundColor": {"r": 0.9, "g": 0.9, "b": 0.9, "a": 1},
                    "flowStartingPoints": [{"nodeId": "1:1", "name": "Flow 1"}],
                    "children": [detail, home],
                }
            ],
        },
    }


def single_frame(children: list[dict[str, Any]], *, w: float = 100, h: float = 100, **frame_extra: Any) -> dict[str, Any]:
    frame = node("9:0", "FRAME", "Frame", 0, 0, w, h, children=children, **frame_extra)
    frame.setdefault("fills", [solid(1, 1, 1)])
    return {
        "name": "Single",
        "document": {
            "id": "0:0",
            "type": "DOCUMENT",
            "name": "Document",
            "children": [{"id": "0:1", "type": "CANVAS", "name": "Page 1", "children": [frame]}],
        },
    }
