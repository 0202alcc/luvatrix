from __future__ import annotations

import random

import pytest

from luvatrix_core import accel


native = pytest.importorskip("luvatrix_core._accel_native")


def test_native_alpha_blit_matches_python_reference_with_and_without_mask() -> None:
    rng = random.Random(314)
    width = 23
    height = 17
    source = bytearray(rng.randrange(256) for _ in range(width * height * 4))
    mask = bytearray(rng.randrange(256) for _ in range(width * height))
    for active_mask in (None, mask):
        expected = bytearray(rng.randrange(256) for _ in range(width * height * 4))
        actual = bytearray(expected)
        accel._native_accel = None
        try:
            accel._alpha_blit_pure(
                accel._PureArray(expected, (height, width, 4)),
                accel._PureArray(bytearray(source), (height, width, 4)),
                accel._PureArray(bytearray(active_mask), (height, width)) if active_mask is not None else None,
                destination_x0=2,
                destination_y0=3,
                source_x0=1,
                source_y0=2,
                copy_width=19,
                copy_height=12,
            )
        finally:
            accel._native_accel = native

        native.alpha_blit_rgba_u8(
            actual,
            width,
            source,
            width,
            active_mask,
            width if active_mask is not None else 0,
            1,
            2,
            3,
            1,
            2,
            19,
            12,
        )
        assert actual == expected


def test_native_solid_mask_blend_matches_python_reference_with_clipping() -> None:
    rng = random.Random(2718)
    frame_width = 29
    frame_height = 19
    mask_width = 17
    mask_height = 13
    mask = bytearray(rng.randrange(256) for _ in range(mask_width * mask_height))
    expected = bytearray(rng.randrange(256) for _ in range(frame_width * frame_height * 4))
    actual = bytearray(expected)
    color = (23, 147, 219, 173)

    accel._blend_solid_mask_rgba_python(
        expected,
        frame_width=frame_width,
        frame_height=frame_height,
        mask_data=mask,
        mask_width=mask_width,
        mask_height=mask_height,
        x=-3,
        y=5,
        color=color,
    )
    native.blend_solid_mask_rgba_u8(
        actual,
        frame_width,
        frame_height,
        mask,
        mask_width,
        mask_height,
        -3,
        5,
        *color,
    )

    assert actual == expected
