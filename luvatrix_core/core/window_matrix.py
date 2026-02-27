from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
import time
from typing import TypeAlias

import torch


LOGGER = logging.getLogger(__name__)
MAGENTA = torch.tensor([255, 0, 255, 255], dtype=torch.uint8)

TensorLike: TypeAlias = torch.Tensor


@dataclass(frozen=True)
class FullRewrite:
    tensor_h_w_4: TensorLike


@dataclass(frozen=True)
class PushColumn:
    index: int
    column_h_4: TensorLike


@dataclass(frozen=True)
class ReplaceColumn:
    index: int
    column_h_4: TensorLike


@dataclass(frozen=True)
class PushRow:
    index: int
    row_w_4: TensorLike


@dataclass(frozen=True)
class ReplaceRow:
    index: int
    row_w_4: TensorLike


@dataclass(frozen=True)
class ReplaceRect:
    x: int
    y: int
    width: int
    height: int
    rect_h_w_4: TensorLike


@dataclass(frozen=True)
class Multiply:
    color_matrix_4x4: TensorLike


WriteOp: TypeAlias = FullRewrite | PushColumn | ReplaceColumn | PushRow | ReplaceRow | ReplaceRect | Multiply


@dataclass(frozen=True)
class WriteBatch:
    operations: list[WriteOp]


@dataclass(frozen=True)
class CallBlitEvent:
    event_id: int
    revision: int
    ts_ns: int


class WindowMatrix:
    """Canonical RGBA255 matrix with atomic write-batch commits."""

    def __init__(self, height: int, width: int, background: tuple[int, int, int, int] = (0, 0, 0, 255)) -> None:
        if height <= 0 or width <= 0:
            raise ValueError("height and width must be > 0")
        self.height = height
        self.width = width
        self._write_lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._event_cv = threading.Condition(self._event_lock)
        self._events: deque[CallBlitEvent] = deque()
        self._next_event_id = 1
        self._revision = 0
        bg = torch.tensor(background, dtype=torch.uint8).view(1, 1, 4)
        self._matrix = bg.expand(height, width, 4).clone()

    @property
    def revision(self) -> int:
        return self._revision

    def read_snapshot(self) -> torch.Tensor:
        """Safe read view for external consumers."""
        with self._write_lock:
            return self._matrix.clone()

    def _unsafe_matrix_view(self) -> torch.Tensor:
        """Internal-only no-copy handle."""
        return self._matrix

    def submit_write_batch(self, batch: WriteBatch) -> CallBlitEvent:
        if not batch.operations:
            raise ValueError("write batch must include at least one operation")

        with self._write_lock:
            staged = self._matrix.clone()
            offending_pixels = 0

            for op in batch.operations:
                staged, op_offending = self._apply_operation(staged, op)
                offending_pixels += op_offending

            if offending_pixels > 0:
                LOGGER.warning(
                    "WindowMatrix write batch sanitized invalid RGBA channels; offending_pixels=%d",
                    offending_pixels,
                )

            self._matrix = staged
            self._revision += 1
            event = CallBlitEvent(
                event_id=self._next_event_id,
                revision=self._revision,
                ts_ns=time.time_ns(),
            )
            self._next_event_id += 1

        with self._event_cv:
            self._events.append(event)
            self._event_cv.notify_all()

        return event

    def pop_call_blit(self, timeout: float | None = None) -> CallBlitEvent | None:
        with self._event_cv:
            if not self._events:
                if timeout is None:
                    return None
                self._event_cv.wait(timeout=timeout)
            if not self._events:
                return None
            return self._events.popleft()

    def pending_call_blit_count(self) -> int:
        with self._event_lock:
            return len(self._events)

    def _apply_operation(self, matrix: torch.Tensor, op: WriteOp) -> tuple[torch.Tensor, int]:
        if isinstance(op, FullRewrite):
            full, offending = _sanitize_rgba_tensor(op.tensor_h_w_4, (self.height, self.width, 4))
            return full, offending
        if isinstance(op, PushColumn):
            _validate_index(op.index, self.width, "column index")
            col, offending = _sanitize_rgba_tensor(op.column_h_4, (self.height, 4))
            if op.index < self.width - 1:
                src = matrix[:, op.index : self.width - 1, :].clone()
                matrix[:, op.index + 1 :, :] = src
            matrix[:, op.index, :] = col
            return matrix, offending
        if isinstance(op, ReplaceColumn):
            _validate_index(op.index, self.width, "column index")
            col, offending = _sanitize_rgba_tensor(op.column_h_4, (self.height, 4))
            matrix[:, op.index, :] = col
            return matrix, offending
        if isinstance(op, PushRow):
            _validate_index(op.index, self.height, "row index")
            row, offending = _sanitize_rgba_tensor(op.row_w_4, (self.width, 4))
            if op.index < self.height - 1:
                src = matrix[op.index : self.height - 1, :, :].clone()
                matrix[op.index + 1 :, :, :] = src
            matrix[op.index, :, :] = row
            return matrix, offending
        if isinstance(op, ReplaceRow):
            _validate_index(op.index, self.height, "row index")
            row, offending = _sanitize_rgba_tensor(op.row_w_4, (self.width, 4))
            matrix[op.index, :, :] = row
            return matrix, offending
        if isinstance(op, ReplaceRect):
            _validate_rect(op.x, op.y, op.width, op.height, self.width, self.height)
            patch, offending = _sanitize_rgba_tensor(op.rect_h_w_4, (op.height, op.width, 4))
            matrix[op.y : op.y + op.height, op.x : op.x + op.width, :] = patch
            return matrix, offending
        if isinstance(op, Multiply):
            color_matrix = _coerce_numeric(op.color_matrix_4x4, (4, 4), "color_matrix_4x4")
            if not torch.isfinite(color_matrix).all():
                raise ValueError("color_matrix_4x4 must contain only finite values")
            out = matrix.to(torch.float32)
            out = torch.matmul(out, color_matrix.transpose(0, 1))
            out = torch.clamp(torch.round(out), 0, 255).to(torch.uint8)
            return out, 0
        raise TypeError(f"Unsupported write op: {type(op)!r}")


def _validate_index(index: int, upper_bound: int, label: str) -> None:
    if index < 0 or index >= upper_bound:
        raise ValueError(f"{label} out of range: {index}")


def _validate_rect(x: int, y: int, width: int, height: int, matrix_width: int, matrix_height: int) -> None:
    if width <= 0 or height <= 0:
        raise ValueError("rect width/height must be > 0")
    if x < 0 or y < 0:
        raise ValueError("rect x/y must be >= 0")
    if x + width > matrix_width or y + height > matrix_height:
        raise ValueError("rect exceeds matrix bounds")


def _coerce_numeric(value: torch.Tensor, expected_shape: tuple[int, ...], label: str) -> torch.Tensor:
    if not torch.is_tensor(value):
        raise ValueError(f"{label} must be a torch.Tensor")
    if tuple(value.shape) != expected_shape:
        raise ValueError(f"{label} has invalid shape: {tuple(value.shape)} expected {expected_shape}")
    if value.dtype == torch.bool:
        return value.to(torch.float32)
    if value.is_floating_point() or value.dtype in (
        torch.int8,
        torch.int16,
        torch.int32,
        torch.int64,
        torch.uint8,
    ):
        return value.to(torch.float32)
    raise ValueError(f"{label} must be a numeric tensor, got {value.dtype}")


def _sanitize_rgba_tensor(value: torch.Tensor, expected_shape: tuple[int, ...]) -> tuple[torch.Tensor, int]:
    raw = _coerce_numeric(value, expected_shape, "rgba tensor")
    invalid = ~torch.isfinite(raw) | (raw < 0) | (raw > 255)
    invalid_pixels = int(torch.any(invalid, dim=-1).sum().item())
    clamped = torch.clamp(raw, 0, 255).to(torch.uint8)
    if invalid_pixels > 0:
        pixel_mask = torch.any(invalid, dim=-1)
        clamped[pixel_mask] = MAGENTA
    return clamped, invalid_pixels
