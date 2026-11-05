"""Parity contract for the optional Rust matrix core (``luvatrix_core._matrix_rs``).

The Rust module is an optional accelerator: when it is absent the pure/numpy/
torch paths must keep behaving exactly as before. These tests therefore skip
when the module is not built, and otherwise assert bit-exact (or documented
tolerance) parity against the existing Python reference implementations.
"""
from __future__ import annotations

import random

import numpy as np
import pytest

from luvatrix_core import accel
from luvatrix_core.core import scene_rasterizer, window_matrix
from luvatrix_core.core.scene_graph import (
    CircleNode,
    ClearNode,
    CpuLayerNode,
    RectNode,
    RoundedRectNode,
    SceneFrame,
    ShaderRectNode,
    TextNode,
)
from luvatrix_core.core.window_matrix import (
    PushColumn,
    PushRow,
    ReplaceColumn,
    ReplaceRect,
    ReplaceRow,
    ShiftFrame,
    WindowMatrix,
    WriteBatch,
)

matrix_rs = pytest.importorskip("luvatrix_core._matrix_rs")


# ---------------------------------------------------------------------------
# alpha_blit_rgba_u8 / blend_solid_mask_rgba_u8 parity with the pure-Python
# reference implementations in luvatrix_core.accel.
# ---------------------------------------------------------------------------


def test_rust_alpha_blit_matches_python_reference_with_and_without_mask() -> None:
    rng = random.Random(314)
    width = 23
    height = 17
    source = bytearray(rng.randrange(256) for _ in range(width * height * 4))
    mask = bytearray(rng.randrange(256) for _ in range(width * height))
    for active_mask in (None, mask):
        expected = bytearray(rng.randrange(256) for _ in range(width * height * 4))
        actual = bytearray(expected)
        saved = accel._native_accel
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
            accel._native_accel = saved

        matrix_rs.alpha_blit_rgba_u8(
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


def test_rust_solid_mask_blend_matches_python_reference_with_clipping() -> None:
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
    matrix_rs.blend_solid_mask_rgba_u8(
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


# ---------------------------------------------------------------------------
# Write-op engine parity with WindowMatrix's numpy semantics.
# ---------------------------------------------------------------------------


def _numpy_reference_apply(buf: np.ndarray, ops: list) -> None:
    """Mirror WindowMatrix._apply_operation semantics with numpy indexing."""
    height, width, _ = buf.shape
    for op in ops:
        if isinstance(op, ReplaceRect):
            patch = np.array(op.rect_h_w_4, dtype=np.uint8).reshape(op.height, op.width, 4)
            buf[op.y : op.y + op.height, op.x : op.x + op.width, :] = patch
        elif isinstance(op, ReplaceRow):
            row = np.array(op.row_w_4, dtype=np.uint8).reshape(width, 4)
            buf[op.index, :, :] = row
        elif isinstance(op, ReplaceColumn):
            col = np.array(op.column_h_4, dtype=np.uint8).reshape(height, 4)
            buf[:, op.index, :] = col
        elif isinstance(op, PushRow):
            row = np.array(op.row_w_4, dtype=np.uint8).reshape(width, 4)
            if op.index < height - 1:
                src = buf[op.index : height - 1, :, :].copy()
                buf[op.index + 1 :, :, :] = src
            buf[op.index, :, :] = row
        elif isinstance(op, PushColumn):
            col = np.array(op.column_h_4, dtype=np.uint8).reshape(height, 4)
            if op.index < width - 1:
                src = buf[:, op.index : width - 1, :].copy()
                buf[:, op.index + 1 :, :] = src
            buf[:, op.index, :] = col
        elif isinstance(op, ShiftFrame):
            fill = np.array(op.fill_rgba_4, dtype=np.uint8).reshape(1, 1, 4)
            dx = int(op.dx)
            dy = int(op.dy)
            out = np.broadcast_to(fill, (height, width, 4)).copy()
            if abs(dx) < width and abs(dy) < height:
                src_x = max(0, -dx)
                dst_x = max(0, dx)
                w = width - abs(dx)
                src_y = max(0, -dy)
                dst_y = max(0, dy)
                h = height - abs(dy)
                if w > 0 and h > 0:
                    out[dst_y : dst_y + h, dst_x : dst_x + w, :] = buf[
                        src_y : src_y + h, src_x : src_x + w, :
                    ]
            buf[:, :, :] = out
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected op: {op!r}")


def _reference_dirty_rect(ops: list, width: int, height: int):
    return window_matrix._dirty_rect_for_operations(ops, width, height)


def _random_ops(rng: random.Random, width: int, height: int) -> list:
    ops = []
    for _ in range(rng.randrange(1, 4)):
        kind = rng.randrange(6)
        if kind == 0:
            x = rng.randrange(width)
            y = rng.randrange(height)
            w = rng.randrange(1, width - x + 1)
            h = rng.randrange(1, height - y + 1)
            payload = [rng.randrange(256) for _ in range(w * h * 4)]
            ops.append(ReplaceRect(x, y, w, h, payload))
        elif kind == 1:
            index = rng.randrange(height)
            payload = [rng.randrange(256) for _ in range(width * 4)]
            ops.append(ReplaceRow(index, payload))
        elif kind == 2:
            index = rng.randrange(width)
            payload = [rng.randrange(256) for _ in range(height * 4)]
            ops.append(ReplaceColumn(index, payload))
        elif kind == 3:
            index = rng.randrange(height)
            payload = [rng.randrange(256) for _ in range(width * 4)]
            ops.append(PushRow(index, payload))
        elif kind == 4:
            index = rng.randrange(width)
            payload = [rng.randrange(256) for _ in range(height * 4)]
            ops.append(PushColumn(index, payload))
        else:
            fill = [rng.randrange(256) for _ in range(4)]
            ops.append(ShiftFrame(rng.randrange(-width, width + 1), rng.randrange(-height, height + 1), fill))
    return ops


def test_rust_apply_ops_matches_numpy_reference_and_dirty_rects() -> None:
    rng = random.Random(90210)
    width = 13
    height = 11
    for _ in range(25):
        initial = [rng.randrange(256) for _ in range(width * height * 4)]
        ops = _random_ops(rng, width, height)

        expected = np.array(initial, dtype=np.uint8).reshape(height, width, 4)
        _numpy_reference_apply(expected, ops)

        actual = bytearray(initial)
        encoded = window_matrix._encode_ops_for_rs(ops)
        assert encoded is not None
        dirty = matrix_rs.apply_ops(actual, width, height, encoded)

        assert bytes(actual) == expected.tobytes(), f"buffer mismatch for ops {ops!r}"
        assert dirty == _reference_dirty_rect(ops, width, height)


def test_rust_apply_ops_rejects_invalid_geometry() -> None:
    buf = bytearray(4 * 4 * 4)
    with pytest.raises(ValueError):
        matrix_rs.apply_ops(buf, 4, 4, window_matrix._encode_ops_for_rs([ReplaceColumn(4, [0] * 16)]))
    with pytest.raises(ValueError):
        matrix_rs.apply_ops(buf, 4, 4, window_matrix._encode_ops_for_rs([ReplaceRect(3, 3, 2, 2, [0] * 16)]))
    with pytest.raises(ValueError):
        matrix_rs.apply_ops(buf, 4, 4, window_matrix._encode_ops_for_rs([PushRow(-1, [0] * 16)]))


# ---------------------------------------------------------------------------
# WindowMatrix integration: identical buffers and events with/without Rust.
# ---------------------------------------------------------------------------


def _run_batch_sequence(ops_sequence: list[list]) -> tuple[list, list]:
    matrix = WindowMatrix(height=11, width=13)
    snapshots = []
    events = []
    for ops in ops_sequence:
        payload_ops = []
        for op in ops:
            payload_ops.append(_with_backend_arrays(op))
        event = matrix.submit_write_batch(WriteBatch(payload_ops))
        events.append((event.revision, event.dirty_rect))
        snapshots.append(accel.to_contiguous_numpy(matrix.read_snapshot()).tobytes())
    return snapshots, events


def _with_backend_arrays(op):
    """Rebuild op payloads through the active accel backend, as real apps do."""
    if isinstance(op, ReplaceRect):
        patch = accel.from_sequence(list(op.rect_h_w_4), (op.height, op.width, 4))
        return ReplaceRect(op.x, op.y, op.width, op.height, patch)
    if isinstance(op, ReplaceRow):
        row = accel.from_sequence(list(op.row_w_4), (len(op.row_w_4) // 4, 4))
        return ReplaceRow(op.index, row)
    if isinstance(op, ReplaceColumn):
        col = accel.from_sequence(list(op.column_h_4), (len(op.column_h_4) // 4, 4))
        return ReplaceColumn(op.index, col)
    if isinstance(op, PushRow):
        row = accel.from_sequence(list(op.row_w_4), (len(op.row_w_4) // 4, 4))
        return PushRow(op.index, row)
    if isinstance(op, PushColumn):
        col = accel.from_sequence(list(op.column_h_4), (len(op.column_h_4) // 4, 4))
        return PushColumn(op.index, col)
    if isinstance(op, ShiftFrame):
        fill = accel.from_sequence(list(op.fill_rgba_4), (1, 1, 4))
        return ShiftFrame(op.dx, op.dy, fill)
    raise AssertionError(f"unexpected op: {op!r}")


def test_window_matrix_produces_identical_results_with_and_without_rust() -> None:
    rng = random.Random(777)
    sequences = [_random_ops(rng, 13, 11) for _ in range(6)]

    saved = window_matrix._matrix_rs_apply
    try:
        window_matrix._matrix_rs_apply = None
        expected_snapshots, expected_events = _run_batch_sequence(sequences)

        window_matrix._matrix_rs_apply = saved
        assert window_matrix._matrix_rs_apply is not None
        actual_snapshots, actual_events = _run_batch_sequence(sequences)
    finally:
        window_matrix._matrix_rs_apply = saved

    assert actual_events == expected_events
    assert actual_snapshots == expected_snapshots


# ---------------------------------------------------------------------------
# Scene lowering parity: Rust fast path vs the Python rasterizer.
# ---------------------------------------------------------------------------


def _frame_with_nodes(nodes: tuple) -> SceneFrame:
    return SceneFrame(
        revision=1,
        logical_width=64,
        logical_height=48,
        display_width=64,
        display_height=48,
        ts_ns=0,
        nodes=nodes,
    )


def _random_layer(rng: random.Random, width: int, height: int) -> np.ndarray:
    return np.array(
        [rng.randrange(256) for _ in range(width * height * 4)], dtype=np.uint8
    ).reshape(height, width, 4)


def _rasterize_pair(frame: SceneFrame):
    expected = scene_rasterizer._rasterize_scene_frame_python(frame)
    actual = scene_rasterizer.rasterize_scene_frame(frame)
    assert scene_rasterizer._last_raster_backend() == "rust"
    return np.asarray(expected), np.asarray(actual)


def test_rust_scene_lowering_matches_python_rasterizer_2d_nodes() -> None:
    rng = random.Random(1234)
    layer = _random_layer(rng, 9, 7)
    frame = _frame_with_nodes(
        (
            ClearNode((10, 20, 30, 255)),
            RectNode(1.5, 2.5, 20.0, 10.0, (200, 30, 40, 255)),
            RectNode(30.0, 5.0, 12.0, 12.0, (10, 220, 40, 128)),
            RoundedRectNode(5.0, 20.0, 25.0, 15.0, 4.0, (90, 90, 200, 255)),
            RoundedRectNode(35.0, 22.0, 18.0, 12.0, 6.0, (200, 160, 20, 100)),
            CircleNode(32.0, 24.0, 10.0, (250, 200, 10, 255), (20, 20, 220, 255), 2.0),
            CircleNode(50.0, 40.0, 6.5, (0, 0, 0, 0), (255, 255, 255, 255), 1.5),
            TextNode("Hi 42", 4.0, 38.0, color_rgba=(255, 255, 0, 255)),
            CpuLayerNode(40.0, 2.0, 9.0, 7.0, layer),
        )
    )
    expected, actual = _rasterize_pair(frame)
    np.testing.assert_array_equal(actual, expected)


def test_rust_scene_lowering_rainbow_shader_within_one_lsb() -> None:
    frame = _frame_with_nodes(
        (
            ClearNode(),
            ShaderRectNode(0.0, 0.0, 64.0, 48.0, "full_suite_background", (0, 0, 0, 255), (123.0, 4.0, 7.0)),
        )
    )
    expected, actual = _rasterize_pair(frame)
    diff = np.abs(actual.astype(np.int16) - expected.astype(np.int16))
    assert int(diff.max()) <= 1


def test_rust_scene_lowering_reuses_output_buffer_and_scales_logical_coords() -> None:
    frame_a = _frame_with_nodes((ClearNode((1, 2, 3, 255)), RectNode(0.0, 0.0, 64.0, 48.0, (9, 9, 9, 255))))
    frame_b = _frame_with_nodes((ClearNode((4, 5, 6, 255)),))
    out = scene_rasterizer.rasterize_scene_frame(frame_a)
    reused = scene_rasterizer.rasterize_scene_frame(frame_b, out=out)
    assert reused is out
    expected = scene_rasterizer._rasterize_scene_frame_python(frame_b)
    np.testing.assert_array_equal(np.asarray(reused), np.asarray(expected))
