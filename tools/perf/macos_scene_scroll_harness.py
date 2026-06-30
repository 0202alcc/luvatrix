from __future__ import annotations

import argparse
from dataclasses import replace
import json
import time

from luvatrix_core.core.scene_graph import ClearNode, RectNode, SceneFrame, SceneGraphBuffer


def run_harness(*, node_count: int, frames: int) -> dict[str, float | int | bool]:
    nodes = (ClearNode((5, 7, 12, 255)),) + tuple(
        RectNode(
            x=float(index % 100) * 12.0,
            y=float(index // 100) * 12.0,
            width=10.0,
            height=10.0,
            color_rgba=(20 + index % 80, 80, 140, 255),
            z_index=1,
        )
        for index in range(node_count)
    )
    buffer = SceneGraphBuffer()
    initial = SceneFrame(
        revision=0,
        logical_width=1280,
        logical_height=720,
        display_width=1280,
        display_height=720,
        ts_ns=1,
        nodes=nodes,
        retained=True,
    )
    buffer.submit(initial)
    retained_nodes = buffer.latest_frame().nodes

    started = time.perf_counter()
    for index in range(frames):
        buffer.submit_content_offset(0.0, float(index))
    transform_elapsed = max(1e-9, time.perf_counter() - started)
    transform_nodes_reused = buffer.latest_frame().nodes is retained_nodes

    started = time.perf_counter()
    for index in range(frames):
        offset = float(index)
        shifted = tuple(
            replace(node, y=node.y - offset) if isinstance(node, RectNode) else node
            for node in nodes
        )
        SceneFrame(0, 1280, 720, 1280, 720, index + 2, shifted)
    rebuild_elapsed = max(1e-9, time.perf_counter() - started)

    return {
        "node_count": node_count,
        "frames": frames,
        "transform_fps": frames / transform_elapsed,
        "rebuild_fps": frames / rebuild_elapsed,
        "speedup": rebuild_elapsed / transform_elapsed,
        "transform_nodes_reused": transform_nodes_reused,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark retained macOS scene scrolling against node rebuilding")
    parser.add_argument("--nodes", type=int, default=5_000)
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--min-transform-fps", type=float, default=60.0)
    args = parser.parse_args()
    result = run_harness(node_count=max(1, args.nodes), frames=max(1, args.frames))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["transform_nodes_reused"]:
        raise SystemExit("retained scene nodes were rebuilt")
    if float(result["transform_fps"]) < args.min_transform_fps:
        raise SystemExit(
            f"transform throughput {result['transform_fps']:.1f} fps is below {args.min_transform_fps:.1f} fps"
        )


if __name__ == "__main__":
    main()
