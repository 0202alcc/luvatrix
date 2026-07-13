from __future__ import annotations

import argparse
import random
import statistics
import time

from luvatrix_core import accel


def _measure(run, *, samples: int) -> float:
    durations = []
    for _ in range(samples):
        started = time.perf_counter()
        run()
        durations.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(durations)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Python and native Android alpha kernels")
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--samples", type=int, default=9)
    args = parser.parse_args()

    try:
        from luvatrix_core import _accel_native as native
    except ImportError as exc:
        raise SystemExit("build with LUVATRIX_BUILD_ACCEL=1 before benchmarking") from exc

    rng = random.Random(314)
    pixel_count = args.width * args.height
    original = bytearray(rng.randrange(256) for _ in range(pixel_count * 4))
    source = bytearray(rng.randrange(256) for _ in range(pixel_count * 4))
    mask = bytearray(rng.randrange(256) for _ in range(pixel_count))

    def run_python() -> None:
        destination = accel._PureArray(bytearray(original), (args.height, args.width, 4))
        previous = accel._native_accel
        accel._native_accel = None
        try:
            accel._alpha_blit_pure(
                destination,
                accel._PureArray(source, (args.height, args.width, 4)),
                accel._PureArray(mask, (args.height, args.width)),
                destination_x0=0,
                destination_y0=0,
                source_x0=0,
                source_y0=0,
                copy_width=args.width,
                copy_height=args.height,
            )
        finally:
            accel._native_accel = previous

    def run_native() -> None:
        destination = bytearray(original)
        native.alpha_blit_rgba_u8(
            destination,
            args.width,
            source,
            args.width,
            mask,
            args.width,
            1,
            0,
            0,
            0,
            0,
            args.width,
            args.height,
        )

    python_ms = _measure(run_python, samples=args.samples)
    native_ms = _measure(run_native, samples=args.samples)
    print(f"python_median_ms={python_ms:.3f}")
    print(f"native_median_ms={native_ms:.3f}")
    print(f"speedup={python_ms / max(native_ms, 1e-9):.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
