"""Drawable alpha probe: analyze a CAMetalDrawable texture readback.

SL-38b: Alec's eyeball said the alpha'd component fills render SOLID over the
behind-window material even though the scene graph carries a<255 fills, the
rasterizer readback is alpha-truthful, and the Metal pipeline is statically
alpha-correct. The remaining question is what the PRESENTED drawable actually
carries before Core Animation composites it. The macOS Metal scene backend
blits the drawable texture into a CPU-readable shared texture on present and
hands the bytes here; this module is pure numpy so it is fully testable off
the Mac.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from luvatrix_core.core.scene_graph import SceneFrame

# Mean-alpha tolerance for flagging a region as matching its scene-derived
# expectation: fixed-point UNORM quantization plus blend rounding stays well
# inside two LSB.
_ALPHA_MATCH_TOLERANCE = 2.0


@dataclass(frozen=True)
class ProbeRegion:
    """One scene-space rectangle to sample in the drawable readback."""

    name: str
    x: float
    y: float
    width: float
    height: float
    expected_alpha: int | None = None
    # When set, the region no longer measures its own fill (e.g. an opaque
    # node covers the sample point), so the match flag is reported as None
    # with this reason instead of a misleading False.
    expected_skipped: str | None = None


@dataclass(frozen=True)
class DrawableProbeCapture:
    """Raw drawable readback stashed by the backend's completed handler."""

    pixels: bytes
    width: int
    height: int
    revision: int
    regions: list | None
    error: str | None = None


def _node_alpha_bounds(node: object) -> tuple[int, float, float, float, float] | None:
    """(alpha, x, y, w, h) for scene nodes that paint a bounded rect-ish area.

    ClearNode covers the whole scene; CircleNode contributes its bounding box.
    Anything else (text/3D/cpu layers) returns None — text coverage is a
    point-model unknown and is handled by the opaque-cover estimate only.
    """
    from luvatrix_core.core.scene_graph import (
        CircleNode,
        ClearNode,
        ImageNode,
        RectNode,
        RoundedRectNode,
        ShaderRectNode,
    )

    if isinstance(node, ClearNode):
        # Covers the whole scene; finite sentinels so bounds math stays sane.
        return (int(node.color_rgba[3]), -1.0e15, -1.0e15, 3.0e15, 3.0e15)
    if isinstance(node, (RectNode, RoundedRectNode, ShaderRectNode)):
        return (int(node.color_rgba[3]), float(node.x), float(node.y), float(node.width), float(node.height))
    if isinstance(node, CircleNode):
        r = float(node.radius)
        return (int(node.fill_rgba[3]), float(node.cx) - r, float(node.cy) - r, 2.0 * r, 2.0 * r)
    if isinstance(node, ImageNode):
        # Album art et al are opaque once decoded; no alpha channel in the node.
        return (255, float(node.x), float(node.y), float(node.width), float(node.height))
    return None


def _covers(bounds: tuple[int, float, float, float, float], px: float, py: float) -> bool:
    _alpha, x, y, w, h = bounds
    return x <= px <= x + w and y <= py <= y + h


def _stack_composite(frame: SceneFrame, upto_index: int, px: float, py: float) -> int:
    """Theoretical source-over alpha at a scene point: every bounded node
    from 0..upto_index (scene order = paint order) whose area covers the
    point, bottom-up. Rounded to the nearest 0..255 unit."""
    out = 0.0
    for node in frame.nodes[: upto_index + 1]:
        bounds = _node_alpha_bounds(node)
        if bounds is None or not _covers(bounds, px, py):
            continue
        src = bounds[0] / 255.0
        out = src + out * (1.0 - src)
    return int(round(out * 255.0))


def _covered_by_opaque(frame: SceneFrame, after_index: int, px: float, py: float) -> bool:
    """Any node ABOVE after_index fully opaque at the point — the region then
    measures the cover, not the fill, so the expectation must be skipped."""
    from luvatrix_core.core.scene_graph import TextNode

    for node in frame.nodes[after_index + 1 :]:
        bounds = _node_alpha_bounds(node)
        if bounds is not None:
            if bounds[0] == 255 and _covers(bounds, px, py):
                return True
            continue
        if isinstance(node, TextNode) and node.text and int(node.color_rgba[3]) == 255:
            width = max(1.0, len(node.text) * float(node.font_size_px) * 0.6)
            if float(node.x) <= px <= float(node.x) + width and float(node.y) <= py <= float(node.y) + float(node.font_size_px):
                return True
    return False


def _fill_regions(frame: SceneFrame) -> list[ProbeRegion]:
    from luvatrix_core.core.scene_graph import RectNode, RoundedRectNode

    regions: list[ProbeRegion] = []
    index = 0
    for node_index, node in enumerate(frame.nodes):
        if not isinstance(node, (RectNode, RoundedRectNode)):
            continue
        alpha = int(node.color_rgba[3])
        if alpha <= 0 or alpha >= 255:
            continue
        # Sample the interior only: AA edges and rounded corners legitimately
        # carry other alphas and would muddy the verdict. Cap the inset at a
        # quarter of the smallest dimension so tiny fills still leave a core.
        min_dim = min(float(node.width), float(node.height))
        inset = min(max(1.0, min_dim * 0.1), min_dim * 0.25)
        width = float(node.width) - 2.0 * inset
        height = float(node.height) - 2.0 * inset
        if width <= 0.0 or height <= 0.0:
            continue
        region_x = float(node.x) + inset
        region_y = float(node.y) + inset
        center_x = region_x + width / 2.0
        center_y = region_y + height / 2.0
        # Composite-aware expectation (SL-38d): the region measures the whole
        # source-over stack beneath this fill, not the fill's own alpha.
        expected = _stack_composite(frame, node_index, center_x, center_y)
        skipped = "covered_by_opaque" if _covered_by_opaque(frame, node_index, center_x, center_y) else None
        regions.append(
            ProbeRegion(
                name=f"fill[{index}]_a{alpha}",
                x=region_x,
                y=region_y,
                width=width,
                height=height,
                expected_alpha=expected,
                expected_skipped=skipped,
            )
        )
        index += 1
    return regions


def _text_regions(frame: SceneFrame) -> list[ProbeRegion]:
    from luvatrix_core.core.scene_graph import TextNode

    regions: list[ProbeRegion] = []
    for index, node in enumerate(frame.nodes):
        if not isinstance(node, TextNode) or not node.text:
            continue
        width = max(1.0, len(node.text) * float(node.font_size_px) * 0.6)
        regions.append(
            ProbeRegion(
                name=f"text[{index}]",
                x=float(node.x),
                y=float(node.y),
                width=width,
                height=float(node.font_size_px),
            )
        )
    return regions


def _gap_region(frame: SceneFrame) -> ProbeRegion:
    from luvatrix_core.core.scene_graph import RectNode, RoundedRectNode

    def _with_stack_expectation(region: ProbeRegion) -> ProbeRegion:
        # The gap's truthful expectation is whatever the whole scene stacks
        # beneath it (usually nothing -> 0, or a full-window tint).
        center_x = region.x + region.width / 2.0
        center_y = region.y + region.height / 2.0
        expected = _stack_composite(frame, len(frame.nodes) - 1, center_x, center_y)
        return ProbeRegion(
            name=region.name,
            x=region.x,
            y=region.y,
            width=region.width,
            height=region.height,
            expected_alpha=expected,
        )

    fills = [
        node
        for node in frame.nodes
        if isinstance(node, (RectNode, RoundedRectNode)) and 0 < int(node.color_rgba[3]) < 255
    ]
    fills.sort(key=lambda node: (float(node.y), float(node.x)))
    for upper, lower in zip(fills, fills[1:]):
        upper_bottom = float(upper.y) + float(upper.height)
        gap = float(lower.y) - upper_bottom
        if gap < 4.0:
            continue
        x0 = max(float(upper.x), float(lower.x))
        x1 = min(float(upper.x) + float(upper.width), float(lower.x) + float(lower.width))
        if x1 - x0 < 4.0:
            continue
        inset = 2.0
        return _with_stack_expectation(
            ProbeRegion(
                name="gap[between_fills]",
                x=x0 + inset,
                y=upper_bottom + gap * 0.25,
                width=x1 - x0 - 2.0 * inset,
                height=gap * 0.5,
            )
        )
    return _with_stack_expectation(ProbeRegion(name="gap[fallback_corner]", x=2.0, y=2.0, width=8.0, height=8.0))


def default_probe_regions(frame: SceneFrame) -> list[ProbeRegion]:
    """Scene-derived sample regions: every translucent fill (with its expected
    alpha), every text run, and one inter-card gap (expected a=0)."""
    return [*_fill_regions(frame), *_text_regions(frame), _gap_region(frame)]


def _coerce_region(raw: object) -> ProbeRegion:
    if isinstance(raw, ProbeRegion):
        return raw
    if isinstance(raw, dict):
        return ProbeRegion(
            name=str(raw.get("name", "region")),
            x=float(raw["x"]),
            y=float(raw["y"]),
            width=float(raw["width"]),
            height=float(raw["height"]),
            expected_alpha=raw.get("expected_alpha"),
            expected_skipped=raw.get("expected_skipped"),
        )
    raise TypeError(f"unsupported probe region: {type(raw)!r}")


def analyze_capture(
    pixels: bytes,
    width: int,
    height: int,
    *,
    viewport: tuple[float, float, float, float],
    logical_size: tuple[float, float],
    regions: list | None,
    revision: int | None = None,
) -> dict[str, Any]:
    """Alpha analysis of one BGRA drawable readback.

    ``viewport`` is the same letterbox viewport the renderer used
    (``_viewport(drawable_w, drawable_h, frame)``); ``logical_size`` is the
    frame's logical extent, so scene-space regions map to pixels exactly the
    way the GPU mapped geometry.
    """
    import numpy as np

    frame_buf = np.frombuffer(pixels, dtype=np.uint8).reshape(int(height), int(width), 4)
    alpha = frame_buf[:, :, 3].astype(np.int32)
    transparent = int(np.count_nonzero(alpha == 0))
    opaque = int(np.count_nonzero(alpha == 255))
    total = int(alpha.size)
    report: dict[str, Any] = {
        "width": int(width),
        "height": int(height),
        "format": "BGRA",
        "alpha": {
            "min": int(alpha.min()) if total else 0,
            "max": int(alpha.max()) if total else 0,
            "transparent_px": transparent,
            "mid_alpha_px": total - transparent - opaque,
            "opaque_px": opaque,
        },
        "regions": [],
    }
    if revision is not None:
        report["revision"] = int(revision)

    vp_x, vp_y, vp_w, vp_h = (float(v) for v in viewport)
    logical_w, logical_h = (float(v) for v in logical_size)
    scale = vp_w / max(1.0, logical_w)
    for raw in regions or []:
        region = _coerce_region(raw)
        px0 = max(0, int(round(vp_x + region.x * scale)))
        py0 = max(0, int(round(vp_y + region.y * scale)))
        px1 = min(int(width), int(round(vp_x + (region.x + region.width) * scale)))
        py1 = min(int(height), int(round(vp_y + (region.y + region.height) * scale)))
        entry: dict[str, Any] = {
            "name": region.name,
            "scene_rect": [region.x, region.y, region.width, region.height],
            "pixel_rect": [px0, py0, max(0, px1 - px0), max(0, py1 - py0)],
        }
        if px1 <= px0 or py1 <= py0:
            entry.update({"n_px": 0, "reason": "region maps outside the drawable"})
        else:
            patch = frame_buf[py0:py1, px0:px1, :].astype(np.float64)
            patch_alpha = patch[:, :, 3]
            entry["n_px"] = int(patch_alpha.size)
            entry["alpha_min"] = int(patch_alpha.min())
            entry["alpha_max"] = int(patch_alpha.max())
            entry["alpha_mean"] = float(patch_alpha.mean())
            # BGRA byte order -> report as RGB.
            entry["rgb_mean"] = [
                float(patch[:, :, 2].mean()),
                float(patch[:, :, 1].mean()),
                float(patch[:, :, 0].mean()),
            ]
            if region.expected_alpha is not None:
                entry["expected_alpha"] = int(region.expected_alpha)
                if region.expected_skipped is not None:
                    # The region no longer measures its own fill (an opaque
                    # node covers the sample point) — report the expectation
                    # but no verdict, rather than a misleading False.
                    entry["expected_skipped"] = region.expected_skipped
                    entry["alpha_matches_expected"] = None
                else:
                    # Compare against the region FLOOR: nodes above the sampled
                    # fill (text, art) only lift max/mean; the least-stacked
                    # pixel carries the bare composite the expectation models.
                    entry["alpha_matches_expected"] = bool(
                        abs(entry["alpha_min"] - float(region.expected_alpha)) <= _ALPHA_MATCH_TOLERANCE
                    )
        report["regions"].append(entry)
    return report
