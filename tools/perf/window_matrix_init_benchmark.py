from __future__ import annotations

import argparse
import builtins
import statistics
import time


def _force_pure_backend_imports() -> None:
    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("force pure backend benchmark")
        if name == "numpy" or name.startswith("numpy."):
            raise ImportError("force pure backend benchmark")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = blocked_import


def _median_ms(run, *, samples: int) -> float:
    durations: list[float] = []
    for _ in range(samples):
        started = time.perf_counter_ns()
        run()
        durations.append((time.perf_counter_ns() - started) / 1_000_000)
    return statistics.median(durations)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark pure-backend WindowMatrix initialization")
    parser.add_argument("--samples", type=int, default=9)
    args = parser.parse_args()
    if args.samples <= 0:
        parser.error("--samples must be > 0")

    _force_pure_backend_imports()
    from luvatrix_core import accel
    from luvatrix_core.core.window_matrix import FullRewrite, WindowMatrix, WriteBatch

    if accel.BACKEND != "pure":
        raise SystemExit(f"expected pure backend, got {accel.BACKEND}")

    for height, width in ((393, 852), (1080, 2400)):
        eager = WindowMatrix(height, width)
        assert eager.is_materialized

        eager_ms = _median_ms(lambda: WindowMatrix(height, width), samples=args.samples)
        lazy_ms = _median_ms(
            lambda: _assert_lazy(WindowMatrix(height, width, lazy=True)),
            samples=args.samples,
        )
        snapshot = eager.read_snapshot()
        rewrite_payload = accel.filled_rgba(height, width, (17, 19, 23, 255))
        snapshot_ms = _median_ms(eager.read_snapshot, samples=args.samples)
        contiguous_ms = _median_ms(
            lambda: _assert_same(accel.to_contiguous_numpy(snapshot), snapshot),
            samples=args.samples,
        )
        upload_bytes_ms = _median_ms(
            lambda: bytes(accel.to_contiguous_numpy(snapshot)._data),
            samples=args.samples,
        )
        first_frame_chain_ms = _median_ms(
            lambda: bytes(accel.to_contiguous_numpy(eager.read_snapshot())._data),
            samples=args.samples,
        )
        rewrite_clone_ms = _median_ms(
            lambda: WindowMatrix(height, width, lazy=True).submit_write_batch(
                WriteBatch([FullRewrite(rewrite_payload)])
            ),
            samples=args.samples,
        )
        rewrite_take_ownership_ms = _median_ms(
            lambda: WindowMatrix(height, width, lazy=True).submit_write_batch(
                WriteBatch([FullRewrite(rewrite_payload, take_ownership=True)])
            ),
            samples=args.samples,
        )
        print(
            f"{height}x{width} eager_allocation_median_ms={eager_ms:.3f} "
            f"lazy_init_median_ms={lazy_ms:.3f}"
        )
        print(
            f"{height}x{width} full_rewrite_clone_median_ms={rewrite_clone_ms:.3f} "
            f"full_rewrite_take_ownership_median_ms={rewrite_take_ownership_ms:.3f}"
        )
        print(
            f"{height}x{width} snapshot_clone_median_ms={snapshot_ms:.3f} "
            f"to_contiguous_median_ms={contiguous_ms:.3f} "
            f"upload_bytes_median_ms={upload_bytes_ms:.3f} "
            f"snapshot_to_upload_bytes_median_ms={first_frame_chain_ms:.3f}"
        )
    return 0


def _assert_lazy(matrix) -> None:
    assert not matrix.is_materialized


def _assert_same(value, expected) -> None:
    assert value is expected


if __name__ == "__main__":
    raise SystemExit(main())
