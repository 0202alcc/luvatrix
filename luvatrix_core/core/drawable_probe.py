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


@dataclass(frozen=True)
class DrawableProbeCapture:
    """Raw drawable readback stashed by the backend's completed handler."""

    pixels: bytes
    width: int
    height: int
    revision: int
    regions: list | None
    error: str | None = None


def _fill_regions(frame: SceneFrame) -> list[ProbeRegion]:
    from luvatrix_core.core.scene_graph import RectNode, RoundedRectNode

    regions: list[ProbeRegion] = []
    index = 0
    for node in frame.nodes:
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
        regions.append(
            ProbeRegion(
                name=f"fill[{index}]_a{alpha}",
                x=float(node.x) + inset,
                y=float(node.y) + inset,
                width=width,
                height=height,
                expected_alpha=alpha,
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
        return ProbeRegion(
            name="gap[between_fills]",
            x=x0 + inset,
            y=upper_bottom + gap * 0.25,
            width=x1 - x0 - 2.0 * inset,
            height=gap * 0.5,
        )
    return ProbeRegion(name="gap[fallback_corner]", x=2.0, y=2.0, width=8.0, height=8.0)


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
                entry["alpha_matches_expected"] = bool(
                    abs(entry["alpha_mean"] - float(region.expected_alpha)) <= _ALPHA_MATCH_TOLERANCE
                )
        report["regions"].append(entry)
    return report
