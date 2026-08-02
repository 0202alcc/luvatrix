"""Measure Matrix viewport traffic without a device-specific GPU timer.

Run with ``uv run python tools/perf/matrix_viewport_harness.py``.  The harness
exercises the production DisplayRuntime and Android bridge contract and reports
the bytes passed to JNI: one initial Matrix upload, then zero-byte viewport
updates that reuse the resident Vulkan texture.
"""
from __future__ import annotations

import argparse
import time

from luvatrix_core import accel
from luvatrix_core.core.display_runtime import DisplayRuntime
from luvatrix_core.core.matrix_viewport import MatrixViewport
from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch
from luvatrix_core.platform.android.vulkan_target import AndroidVulkanBridge, AndroidVulkanTarget


class _TrafficPresenter:
    def __init__(self) -> None:
        self.upload_bytes = 0
        self.viewport_presents = 0

    def present_rgba_viewport(self, rgba: bytes, *_args: object) -> None:
        self.upload_bytes += len(rgba)
        self.viewport_presents += 1

    def present_rgba_region_viewport(self, rgba: bytes, *_args: object) -> None:
        self.upload_bytes += len(rgba)
        self.viewport_presents += 1

    def present_viewport(self, *_args: object) -> None:
        self.viewport_presents += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure retained Matrix viewport JNI traffic")
    parser.add_argument("--width", type=int, default=540)
    parser.add_argument("--content-height", type=int, default=2400)
    parser.add_argument("--viewport-height", type=int, default=1200)
    parser.add_argument("--steps", type=int, default=120)
    args = parser.parse_args()
    if min(args.width, args.content_height, args.viewport_height, args.steps) <= 0:
        parser.error("dimensions and steps must be > 0")
    if args.viewport_height > args.content_height:
        parser.error("viewport height cannot exceed content height")

    matrix = WindowMatrix(height=args.content_height, width=args.width)
    presenter = _TrafficPresenter()
    target = AndroidVulkanTarget(AndroidVulkanBridge(presenter))
    runtime = DisplayRuntime(matrix, target)
    target.start()
    try:
        matrix.set_presentation_viewport(MatrixViewport(0, 0, args.width, args.viewport_height))
        matrix.submit_write_batch(WriteBatch([FullRewrite(accel.zeros((args.content_height, args.width, 4)))]))
        runtime.run_once(timeout=0.01)
        initial_upload_bytes = presenter.upload_bytes
        started = time.perf_counter_ns()
        for step in range(args.steps):
            y = step % (args.content_height - args.viewport_height + 1)
            matrix.set_presentation_viewport(MatrixViewport(0, y, args.width, args.viewport_height))
            runtime.run_once(timeout=0.01)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    finally:
        target.stop()

    print(f"initial_upload_bytes={initial_upload_bytes}")
    print(f"viewport_update_upload_bytes={presenter.upload_bytes - initial_upload_bytes}")
    print(f"viewport_presents={presenter.viewport_presents}")
    print(f"viewport_updates_elapsed_ms={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
