"""Post-process the captured Nomic design into a phone/tablet demo app.

Merges the separately captured logged-out sign-in frame into the multi-page
app capture (remapping its node ids so they cannot collide), renames frames
after their capture paths, and renames interaction hotspots after their
destination frame so `tour.json` can tap them by name. Run after
`luvatrix figma capture`:

    python postprocess_capture.py <app_design_dir> --login-capture <dir>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _flatten(node: dict) -> list[dict]:
    out = [node]
    for child in node.get("children") or ():
        out.extend(_flatten(child))
    return out


def _remap_ids(node: dict, prefix: str) -> None:
    if "id" in node and isinstance(node["id"], str) and ":" in node["id"]:
        node["id"] = prefix + node["id"]
    actions = (node.get("interactions") or [{}])[0].get("actions") or []
    for action in actions:
        destination = action.get("destinationId")
        if isinstance(destination, str) and ":" in destination:
            action["destinationId"] = prefix + destination
    for child in node.get("children") or ():
        _remap_ids(child, prefix)


def _merge_login(design: dict, login: dict, login_clickables: list[dict], home_frame_id: str) -> int:
    canvas = design["document"]["children"][0]
    login_canvas = login["document"]["children"][0]
    _remap_ids(login_canvas, "L")
    frame = login_canvas["children"][0]
    frame["name"] = "Sign In"
    # The app boots onto the first top-level frame, so the sign-in screen
    # leads the tour.
    canvas["children"].insert(0, frame)

    wired = 0
    for clickable in login_clickables:
        if clickable.get("selector") != "button" or clickable.get("page") != "/login":
            continue
        node = next(
            (n for n in _flatten(frame) if n.get("id") == "L" + str(clickable["nodeId"])),
            None,
        )
        if node is None:
            continue
        node["interactions"] = [
            {
                "trigger": {"type": "ON_CLICK"},
                "actions": [
                    {
                        "type": "NODE",
                        "destinationId": home_frame_id,
                        "navigation": "NAVIGATE",
                        "transition": None,
                    }
                ],
            }
        ]
        wired += 1
    return wired


def _frame_labels(design: dict, design_dir: Path) -> dict[str, str]:
    labels: dict[str, str] = {}
    report_path = design_dir / "capture_report.json"
    if report_path.exists():
        report = _load(report_path)
        for page in report.get("pages") or ():
            segment = [part for part in str(page.get("path", "")).split("/") if part]
            label = segment[-1].replace("-", " ").title() if segment else "Home"
            labels[str(page.get("frameId"))] = label or "Home"
    for frame in design["document"]["children"][0]["children"]:
        labels.setdefault(str(frame["id"]), frame["name"])
    return labels


def rename_hotspots(design: dict, design_dir: Path) -> int:
    canvas = design["document"]["children"][0]
    labels = _frame_labels(design, design_dir)
    for frame in canvas["children"]:
        frame["name"] = labels.get(str(frame["id"]), frame["name"])
    renamed = 0
    for frame in canvas["children"]:
        for node in _flatten(frame):
            actions = (node.get("interactions") or [{}])[0].get("actions") or []
            destination = next(
                (a.get("destinationId") for a in actions if a.get("destinationId")),
                None,
            )
            if not destination:
                continue
            if frame["name"] == "Sign In":
                node["name"] = "Sign In Button"
            else:
                node["name"] = f"{labels.get(str(destination), 'Page')} Link"
            renamed += 1
    return renamed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design_dir", type=Path)
    parser.add_argument("--login-capture", type=Path, required=True)
    args = parser.parse_args()

    design = args.design_dir / "figma_file.json"
    payload = _load(design)
    login = _load(args.login_capture / "figma_file.json")
    login_clickables = _load(args.login_capture / "clickables.json")

    home_frame = payload["document"]["children"][0]["children"][0]
    wired = _merge_login(payload, login, login_clickables, str(home_frame["id"]))
    renamed = rename_hotspots(payload, args.design_dir)
    design.write_text(json.dumps(payload), encoding="utf-8")
    print(
        f"[nomic_app] merged login frame (wired {wired} button), "
        f"renamed {renamed} hotspot(s)"
    )


if __name__ == "__main__":
    main()