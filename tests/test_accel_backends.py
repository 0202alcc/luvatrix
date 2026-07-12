from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest


def _flat_values(x):
    if hasattr(x, "_data"):
        return list(x._data)
    if hasattr(x, "detach"):
        return x.detach().cpu().reshape(-1).tolist()
    return x.reshape(-1).tolist()


class AccelBackendTests(unittest.TestCase):
    def test_blit_places_and_clips_tile_on_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.zeros((3, 4, 1))
        tile = accel.from_sequence([1, 2, 3, 4, 5, 6], (2, 3, 1))

        result = accel.blit(frame, tile, x=2, y=1)

        self.assertIs(result, frame)
        self.assertEqual(
            _flat_values(frame),
            [0, 0, 0, 0, 0, 0, 1, 2, 0, 0, 4, 5],
        )

    def test_blit_clips_negative_origin_on_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.zeros((2, 2, 1))
        tile = accel.from_sequence(list(range(1, 10)), (3, 3, 1))

        accel.blit(frame, tile, x=-1, y=-1)

        self.assertEqual(_flat_values(frame), [5, 6, 8, 9])

    def test_blit_ignores_fully_offscreen_tile_on_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence([7, 7, 7, 7], (2, 2, 1))
        tile = accel.from_sequence([1], (1, 1, 1))

        accel.blit(frame, tile, x=2, y=0)

        self.assertEqual(_flat_values(frame), [7, 7, 7, 7])

    def test_blit_self_copy_uses_source_snapshot_on_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence([1, 2, 3, 4], (4, 1, 1))

        accel.blit(frame, frame, x=0, y=1)

        self.assertEqual(_flat_values(frame), [1, 1, 2, 3])

    def test_alpha_blit_composites_rgba_and_preserves_transparent_pixels(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence([10, 20, 30, 255] * 2, (1, 2, 4))
        tile = accel.from_sequence(
            [110, 120, 130, 128, 200, 210, 220, 0],
            (1, 2, 4),
        )

        result = accel.alpha_blit(frame, tile, x=0, y=0)

        self.assertIs(result, frame)
        self.assertEqual(_flat_values(frame), [60, 70, 80, 255, 10, 20, 30, 255])

    def test_alpha_blit_applies_optional_coverage_mask(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence([10, 20, 30, 255], (1, 1, 4))
        tile = accel.from_sequence([110, 120, 130, 255], (1, 1, 4))
        mask = accel.from_sequence([128], (1, 1, 1))

        accel.alpha_blit(frame, tile, x=0, y=0, mask=mask)

        self.assertEqual(_flat_values(frame), [60, 70, 80, 255])

    def test_alpha_blit_clips_negative_origin(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence([10, 20, 30, 255], (1, 1, 4))
        tile = accel.from_sequence(
            [0, 0, 0, 0] * 3 + [110, 120, 130, 128],
            (2, 2, 4),
        )

        accel.alpha_blit(frame, tile, x=-1, y=-1)

        self.assertEqual(_flat_values(frame), [60, 70, 80, 255])

    def test_accel_imports_when_torch_is_unavailable(self) -> None:
        code = r'''
import builtins
real_import = builtins.__import__
def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch."):
        raise ImportError("blocked torch for android test")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = blocked_import
from luvatrix_core import accel
from luvatrix_core.platform.frame_pipeline import PresentationMode
assert accel.BACKEND in ("numpy", "pure"), accel.BACKEND
assert accel.zeros((1, 1, 4)).shape == (1, 1, 4)
if accel.BACKEND == "numpy":
    rgba = accel.from_sequence([10, 20, 30, 255], (1, 1, 4))
    overlay = accel.from_sequence([110, 120, 130, 128], (1, 1, 4))
    accel.alpha_blit(rgba, overlay, x=0, y=0)
    assert rgba.reshape(-1).tolist() == [60, 70, 80, 255], rgba
assert PresentationMode.STRETCH.value == "stretch"
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_roll_shifts_rows_on_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence(list(range(24)), (3, 2, 4))
        rolled = accel.roll(frame, 1, dims=0)

        self.assertEqual(_flat_values(rolled), list(range(16, 24)) + list(range(16)))

    def test_roll_wraps_negative_shift_on_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence(list(range(6)), (2, 3, 1))
        rolled = accel.roll(frame, -1, dims=1)

        self.assertEqual(_flat_values(rolled), [1, 2, 0, 4, 5, 3])

    def test_roll_without_dims_rolls_flattened_active_backend(self) -> None:
        from luvatrix_core import accel

        frame = accel.from_sequence(list(range(6)), (2, 3, 1))
        rolled = accel.roll(frame, 2)

        self.assertEqual(_flat_values(rolled), [4, 5, 0, 1, 2, 3])

    def test_roll_dispatches_numpy_arrays_under_torch_selected_backend(self) -> None:
        code = r'''
import sys
import types

fake_torch = types.ModuleType("torch")
fake_torch.uint8 = object()
fake_torch.is_tensor = lambda value: False
def roll(*args, **kwargs):
    raise AssertionError("torch.roll should not receive numpy arrays")
fake_torch.roll = roll
sys.modules["torch"] = fake_torch

from luvatrix_core import accel
import numpy as np

assert accel.BACKEND == "torch", accel.BACKEND
frame = np.arange(6, dtype=np.uint8).reshape((2, 3, 1))
rolled = accel.roll(frame, -1, dims=1)
assert rolled.reshape(-1).tolist() == [1, 2, 0, 4, 5, 3], rolled
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_roll_works_in_pure_python_backend(self) -> None:
        code = r'''
import builtins
real_import = builtins.__import__
def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch.") or name == "numpy" or name.startswith("numpy."):
        raise ImportError("blocked numeric backend for pure accel test")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = blocked_import
from luvatrix_core import accel
assert accel.BACKEND == "pure", accel.BACKEND
frame = accel.from_sequence(list(range(24)), (3, 2, 4))
rolled = accel.roll(frame, 1, dims=0)
assert list(rolled._data) == list(range(16, 24)) + list(range(16)), list(rolled._data)
rolled_axis = accel.roll(accel.from_sequence(list(range(6)), (2, 3, 1)), -1, dims=1)
assert list(rolled_axis._data) == [1, 2, 0, 4, 5, 3], list(rolled_axis._data)
rolled_flat = accel.roll(accel.from_sequence(list(range(6)), (2, 3, 1)), 2)
assert list(rolled_flat._data) == [4, 5, 0, 1, 2, 3], list(rolled_flat._data)
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_blit_works_in_pure_python_backend(self) -> None:
        code = r'''
import builtins
real_import = builtins.__import__
def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch.") or name == "numpy" or name.startswith("numpy."):
        raise ImportError("blocked numeric backend for pure accel test")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = blocked_import
from luvatrix_core import accel
from luvatrix.app import draw_rounded_rect_to_matrix
assert accel.BACKEND == "pure", accel.BACKEND
frame = accel.zeros((3, 4, 4))
tile = accel.from_sequence(list(range(1, 25)), (2, 3, 4))
result = accel.blit(frame, tile, x=2, y=1)
assert result is frame
expected = [0] * 24 + list(range(1, 9)) + [0] * 8 + list(range(13, 21))
assert list(frame._data) == expected, list(frame._data)
clipped = accel.zeros((2, 2, 1))
accel.blit(clipped, accel.from_sequence(list(range(1, 10)), (3, 3, 1)), x=-1, y=-1)
assert list(clipped._data) == [5, 6, 8, 9], list(clipped._data)
self_copy = accel.from_sequence([1, 2, 3, 4], (4, 1, 1))
accel.blit(self_copy, self_copy, x=0, y=1)
assert list(self_copy._data) == [1, 1, 2, 3], list(self_copy._data)
rgba = accel.from_sequence([10, 20, 30, 255] * 2, (1, 2, 4))
overlay = accel.from_sequence([110, 120, 130, 128, 200, 210, 220, 0], (1, 2, 4))
accel.alpha_blit(rgba, overlay, x=0, y=0)
assert list(rgba._data) == [60, 70, 80, 255, 10, 20, 30, 255], list(rgba._data)
rounded = accel.from_sequence([255, 250, 232, 255] * (8 * 12), (8, 12, 4))
draw_rounded_rect_to_matrix(
    rounded,
    x=2,
    y=1,
    width=8,
    height=6,
    radius=3,
    color=(65, 105, 225, 255),
)
def pixel(frame, y, x):
    start = (y * 12 + x) * 4
    return tuple(frame._data[start:start + 4])
assert pixel(rounded, 1, 2) == (255, 250, 232, 255), pixel(rounded, 1, 2)
assert pixel(rounded, 4, 3) == (65, 105, 225, 255), pixel(rounded, 4, 3)
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_full_suite_imports_without_torch(self) -> None:
        code = r'''
import builtins
real_import = builtins.__import__
def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "torch" or name.startswith("torch."):
        raise ImportError("blocked torch for android test")
    return real_import(name, globals, locals, fromlist, level)
builtins.__import__ = blocked_import
import examples.full_suite_interactive.app_main as app
assert app.FullSuiteInteractiveApp is not None
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
