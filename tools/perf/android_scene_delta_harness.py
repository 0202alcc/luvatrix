from __future__ import annotations

import argparse
import statistics
import time

from luvatrix_core.core.scene_graph import ClearNode, RectNode, SceneFrame
from luvatrix_core.platform.android.scene_target import AndroidNativeSceneTarget


class _Presenter:
    def presentScene(self, *_args) -> None:
        return

    def presentSceneTransform(self, *_args) -> None:
        return


def _median_ms(run, *, samples: int) -> float:
    durations = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        run()
        durations.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return statistics.median(durations)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure Android retained-scene delta transport")
    parser.add_argument("--nodes", type=int, default=5_000)
    parser.add_argument("--samples", type=int, default=21)
    args = parser.parse_args()

    nodes = (ClearNode((10, 12, 16, 255)),) + tuple(
        RectNode(
            float(index % 100) * 12.0,
            float(index // 100) * 8.0,
            10.0,
            6.0,
            (index % 255, 140, 220, 255),
        )
        for index in range(max(0, args.nodes))
    )
    presenter = _Presenter()
    target = AndroidNativeSceneTarget(presenter)
    target.start()
    revision = 0

    def next_frame(*, retained: bool) -> SceneFrame:
        nonlocal revision
        revision += 1
        return SceneFrame(
            revision,
            1_200,
            2_400,
            1_200,
            2_400,
            time.time_ns(),
            nodes,
            content_offset_y=float(revision),
            retained=retained,
        )

    target.present_scene(next_frame(retained=True))
    full_ms = _median_ms(lambda: target.present_scene(next_frame(retained=False)), samples=args.samples)
    target.present_scene(next_frame(retained=True))
    delta_ms = _median_ms(lambda: target.present_scene(next_frame(retained=True)), samples=args.samples)
    print(f"nodes={len(nodes)}")
    print(f"full_transport_median_ms={full_ms:.3f}")
    print(f"delta_transport_median_ms={delta_ms:.3f}")
    print(f"transport_speedup={full_ms / max(delta_ms, 1e-9):.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
