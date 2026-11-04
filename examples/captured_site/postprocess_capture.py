"""Post-process a captured multi-page design into a phone-sized demo app.

Drops captured content below `MAX_HEIGHT` points (composed transforms decide
what is actually visible there), renames interaction hotspots after their
destination frame so `tour.json` can tap them by name, and rewrites each
frame's height. Run after `luvatrix figma capture`:

    python postprocess_capture.py <design_dir> [--max-height 2560]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from luvatrix_ui.figma.document import FigmaDocument, node_transform
from luvatrix_ui.figma.geometry import Affine

MAX_HEIGHT = 2560.0


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten(node: dict) -> list[dict]:
    out = [node]
    for child in node.get("children") or ():
        out.extend(_flatten(child))
    return out


def _drop_ids(node: dict, doomed: set[str]) -> None:
    children = node.get("children")
    if not children:
        return
    kept = [child for child in children if str(child.get("id")) not in doomed]
    node["children"] = kept
    for child in kept:
        _drop_ids(child, doomed)


def truncate(payload: dict, max_height: float) -> None:
    canvas = payload["document"]["children"][0]
    for frame in canvas["children"]:
        doomed: set[str] = set()
        for node, tf in _walk_shim(frame, Affine.identity()):
            if tf.ty >= max_height:
                doomed.add(str(node.get("id")))
        _drop_ids(frame, doomed)
        height = float(frame["absoluteBoundingBox"]["height"])
        frame["absoluteBoundingBox"]["height"] = min(height, max_height)
        # Phone-sized viewport: the captured page scrolls inside the app frame
        # instead of being scaled down to fit.
        frame["overflowDirection"] = "VERTICAL_SCROLLING"


def _walk_shim(node: dict, container: Affine):
    from luvatrix_ui.figma.document import TRANSPARENT_CONTAINERS

    for child in node.get("children") or ():
        rel = child.get("relativeTransform")
        if isinstance(rel, list) and len(rel) == 2 and "size" in child:
            tf = container @ Affine.from_figma(rel)
        else:
            bbox = child.get("absoluteBoundingBox") or {}
            tf = Affine.translate(float(bbox.get("x", 0.0)), float(bbox.get("y", 0.0)))
        yield child, tf
        yield from _walk_shim(child, container if child.get("type") in TRANSPARENT_CONTAINERS else tf)


def rename_hotspots(payload: dict, design_dir: Path) -> int:
    canvas = payload["document"]["children"][0]
    labels = _frame_labels(payload, design_dir)
    for frame in canvas["children"]:
        frame["name"] = labels.get(str(frame["id"]), frame["name"])
    renamed = 0
    for frame in canvas["children"]:
        for node in _flatten(frame):
            actions = (node.get("interactions") or [{}])[0].get("actions") or []
            destination = next((a.get("destinationId") for a in actions if a.get("destinationId")), None)
            if not destination:
                continue
            node["name"] = f"{labels.get(str(destination), 'Page')} Link"
            renamed += 1
    return renamed


def _frame_labels(payload: dict, design_dir: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    report_path = design_dir / "capture_report.json"
    if report_path.exists():
        report = _load(report_path)
        for index, page in enumerate(report.get("pages") or ()):
            path = str(page.get("path", f"page{index}"))
            segment = [part for part in path.split("/") if part]
            label = segment[-1].replace("-", " ").title() if segment else "Home"
            labels[str(page.get("frameId"))] = label or "Home"
    if not labels:
        for index, frame in enumerate(payload["document"]["children"][0]["children"]):
            labels[str(frame["id"])] = f"Page {index + 1}"
    return labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_dir", type=Path)
    parser.add_argument("--max-height", type=float, default=MAX_HEIGHT)
    args = parser.parse_args()

    design = args.design_dir / "figma_file.json"
    payload = _load(design)
    truncate(payload, args.max_height)
    renamed = rename_hotspots(payload, args.design_dir)
    design.write_text(json.dumps(payload), encoding="utf-8")
    print(f"[captured_site] truncated frames to {args.max_height}pt, renamed {renamed} hotspot(s)")


if __name__ == "__main__":
    main()