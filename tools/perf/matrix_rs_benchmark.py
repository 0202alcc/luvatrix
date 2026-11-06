"""Benchmark the optional Rust matrix core against the Python reference paths.

Compares, per workload, the existing pure/numpy implementation against
``luvatrix_core._matrix_rs``:

- ``alpha_blit``: pure-Python per-pixel loop vs Rust blit (pure backend).
- ``write_batch``: WindowMatrix staged-clone path vs Rust in-place op engine.
- ``scene_rasterize``: Python scene rasterizer vs Rust scene lowering.
- ``viewport_crop``: pure-Python per-pixel viewport loop vs Rust present crop.

Usage::

    uv run python tools/perf/matrix_rs_benchmark.py --iterations 40
"""

from __future__ import annotations

import argparse
import json
import random
import time

from luvatrix_core import accel
from luvatrix_core.core import display_runtime, scene_rasterizer, window_matrix
from luvatrix_core.core.matrix_viewport import MatrixViewport
from luvatrix_core.core.scene_graph import (
    Camera3DNode,
    CircleNode,
    ClearNode,
    Cube3DNode,
    DotGrid3DNode,
    DotPlane3DNode,
    GroundPlane3DNode,
    Horizon3DNode,
    Line3DNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
    ShaderRectNode,
    Text3DNode,
)
from luvatrix_core.core.window_matrix import (
    PushRow,
    ReplaceRect,
    ReplaceRow,
    ShiftFrame,
    WindowMatrix,
    WriteBatch,
)

matrix_rs = __import__("luvatrix_core._matrix_rs", fromlist=["_matrix_rs"])


def _time_ns(fn, iterations: int) -> int:
    started = time.perf_counter_ns()
    for _ in range(iterations):
        fn()
    return max(1, (time.perf_counter_ns() - started) // iterations)


def _bench_alpha_blit(iterations: int) -> dict[str, float | str]:
    width, height = 320, 240
    rng = random.Random(2024)
    source = accel._PureArray(bytearray(rng.randrange(256) for _ in range(width * height * 4)), (height, width, 4))
    frame = accel._PureArray(bytearray(rng.randrange(256) for _ in range(width * height * 4)), (height, width, 4))

    def run_with(native) -> int:
        saved_rs, saved_native = accel._rs_accel, accel._native_accel
        accel._rs_accel = native
        accel._native_accel = None
        try:
            return _time_ns(
                lambda: accel._alpha_blit_pure(
                    frame,
                    source,
                    None,
                    destination_x0=0,
                    destination_y0=0,
                    source_x0=0,
                    source_y0=0,
                    copy_width=width,
                    copy_height=height,
                ),
                iterations,
            )
        finally:
            accel._rs_accel, accel._native_accel = saved_rs, saved_native

    python_ns = run_with(None)
    rust_ns = run_with(matrix_rs)
    return {
        "workload": "alpha_blit_320x240",
        "python_ns_per_op": float(python_ns),
        "rust_ns_per_op": float(rust_ns),
        "speedup": round(python_ns / rust_ns, 2),
    }


def _sample_ops(rng: random.Random, width: int, height: int) -> list:
    ops = []
    for _ in range(6):
        kind = rng.randrange(4)
        if kind == 0:
            x = rng.randrange(width // 2)
            y = rng.randrange(height // 2)
            w, h = width // 4, height // 4
            payload = accel.from_sequence([rng.randrange(256) for _ in range(w * h * 4)], (h, w, 4))
            ops.append(ReplaceRect(x, y, w, h, payload))
        elif kind == 1:
            row = accel.from_sequence([rng.randrange(256) for _ in range(width * 4)], (width, 4))
            ops.append(ReplaceRow(rng.randrange(height), row))
        elif kind == 2:
            row = accel.from_sequence([rng.randrange(256) for _ in range(width * 4)], (width, 4))
            ops.append(PushRow(rng.randrange(height), row))
        else:
            fill = accel.from_sequence([rng.randrange(256) for _ in range(4)], (1, 1, 4))
            ops.append(ShiftFrame(rng.randrange(-8, 9), rng.randrange(-8, 9), fill))
    return ops


def _bench_write_batch(iterations: int) -> dict[str, float | str]:
    width, height = 320, 240
    rng = random.Random(777)
    ops = _sample_ops(rng, width, height)

    def run_with(rs_apply) -> int:
        saved = window_matrix._matrix_rs_apply
        window_matrix._matrix_rs_apply = rs_apply
        try:
            matrix = WindowMatrix(height=height, width=width)
            return _time_ns(lambda: matrix.submit_write_batch(WriteBatch(ops)), iterations)
        finally:
            window_matrix._matrix_rs_apply = saved

    python_ns = run_with(None)
    rust_ns = run_with(matrix_rs.apply_ops)
    return {
        "workload": f"write_batch_{len(ops)}ops_{width}x{height}",
        "python_ns_per_op": float(python_ns),
        "rust_ns_per_op": float(rust_ns),
        "speedup": round(python_ns / rust_ns, 2),
    }


def _sample_frame(width: int, height: int, node_count: int) -> SceneFrame:
    rng = random.Random(99)
    nodes: list = [ClearNode((12, 10, 18, 255))]
    for index in range(node_count):
        kind = index % 3
        x = float(rng.randrange(0, max(1, width - 80)))
        y = float(rng.randrange(0, max(1, height - 80)))
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256), rng.randrange(256))
        if kind == 0:
            nodes.append(RectNode(x, y, 64.0, 40.0, color))
        elif kind == 1:
            nodes.append(RoundedRectNode(x, y, 72.0, 48.0, 9.0, color))
        else:
            nodes.append(CircleNode(x + 32.0, y + 24.0, 22.0, color, (255, 255, 255, 255), 2.0))
    nodes.append(
        ShaderRectNode(0.0, 0.0, float(width), float(height), "full_suite_background", (0, 0, 0, 255), (3.0, 1.0, 2.0))
    )
    return SceneFrame(
        revision=1,
        logical_width=width,
        logical_height=height,
        display_width=width,
        display_height=height,
        ts_ns=0,
        nodes=tuple(nodes),
    )


def _bench_scene_rasterize(iterations: int) -> dict[str, float | str]:
    width, height = 640, 360
    frame = _sample_frame(width, height, 60)
    python_ns = _time_ns(lambda: scene_rasterizer._rasterize_scene_frame_python(frame), iterations)
    rust_ns = _time_ns(lambda: scene_rasterizer._rasterize_scene_frame_rs(frame), iterations)
    return {
        "workload": f"scene_rasterize_{width}x{height}_61nodes",
        "python_ns_per_op": float(python_ns),
        "rust_ns_per_op": float(rust_ns),
        "speedup": round(python_ns / rust_ns, 2),
    }


def _sample_frame_3d(width: int, height: int) -> SceneFrame:
    nodes = [
        ClearNode((10, 12, 18, 255)),
        Camera3DNode(position=(0.0, 2.0, 6.0), target=(0.0, 0.5, 0.0)),
        Horizon3DNode(sky_horizon_rgba=(200, 210, 220, 255)),
        GroundPlane3DNode(center=(0.0, -1.0, -5.0), width=8.0, depth=6.0),
        DotGrid3DNode(center=(0.5, 0.5, -1.0), extent=4.0, spacing=0.5, point_size=2.0),
        DotPlane3DNode(center=(0.0, -0.5, -2.0), width=6.0, depth=4.0, spacing=0.75, point_size=1.5),
        Cube3DNode(center=(0.0, 0.5, 0.0), size=1.4, rotation=(0.3, 0.7, 0.1)),
        Line3DNode(start=(-2.0, 0.0, 0.0), end=(2.0, 1.0, -1.0)),
        Text3DNode(text="FPS 60", position=(0.0, 1.5, -1.0), height=0.4),
    ]
    return SceneFrame(
        revision=1,
        logical_width=width,
        logical_height=height,
        display_width=width,
        display_height=height,
        ts_ns=0,
        nodes=tuple(nodes),
    )


def _bench_scene_rasterize_3d(iterations: int) -> dict[str, float | str]:
    width, height = 640, 360
    frame = _sample_frame_3d(width, height)
    python_ns = _time_ns(lambda: scene_rasterizer._rasterize_scene_frame_python(frame), iterations)
    rust_ns = _time_ns(lambda: scene_rasterizer._rasterize_scene_frame_rs(frame), iterations)
    return {
        "workload": f"scene_rasterize_3d_{width}x{height}_9nodes",
        "python_ns_per_op": float(python_ns),
        "rust_ns_per_op": float(rust_ns),
        "speedup": round(python_ns / rust_ns, 2),
    }


def _python_crop_loop(snapshot, viewport: MatrixViewport):
    output = accel.zeros((viewport.height, viewport.width, 4))
    for destination_y in range(viewport.height):
        source_y = (viewport.y + destination_y) % snapshot.shape[0] if viewport.wrap_y else viewport.y + destination_y
        for destination_x in range(viewport.width):
            source_x = (viewport.x + destination_x) % snapshot.shape[1] if viewport.wrap_x else viewport.x + destination_x
            output[destination_y, destination_x, :] = snapshot[source_y, source_x, :]
    return output


def _bench_viewport_crop(iterations: int) -> dict[str, float | str]:
    import numpy as np

    width, height = 1280, 720
    rng = np.random.default_rng(2027)
    np_snapshot = rng.integers(0, 256, size=(height, width, 4), dtype=np.uint8)
    # Match the active accel backend so the Python reference loop mixes the
    # same array kinds it would in production.
    torch = accel._torch
    snapshot = torch.from_numpy(np_snapshot) if torch is not None else np_snapshot
    viewport = MatrixViewport(x=977, y=533, width=640, height=360, wrap_x=True, wrap_y=True)
    python_ns = _time_ns(lambda: _python_crop_loop(snapshot, viewport), max(1, iterations // 30))
    rust_ns = _time_ns(lambda: display_runtime._crop_viewport(snapshot, viewport), iterations)
    return {
        "workload": f"viewport_crop_wrap_{viewport.width}x{viewport.height}_of_{width}x{height}",
        "python_ns_per_op": float(python_ns),
        "rust_ns_per_op": float(rust_ns),
        "speedup": round(python_ns / rust_ns, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    results = [
        _bench_alpha_blit(args.iterations),
        _bench_write_batch(args.iterations),
        _bench_scene_rasterize(max(3, args.iterations // 6)),
        _bench_scene_rasterize_3d(max(3, args.iterations // 6)),
        _bench_viewport_crop(args.iterations),
    ]
    print(f"{'workload':<38} {'python ns/op':>14} {'rust ns/op':>14} {'speedup':>9}")
    for row in results:
        print(
            f"{row['workload']:<38} {row['python_ns_per_op']:>14.0f} "
            f"{row['rust_ns_per_op']:>14.0f} {row['speedup']:>8}x"
        )
    print(json.dumps({"benchmark": "matrix_rs", "results": results}))


if __name__ == "__main__":
    main()
