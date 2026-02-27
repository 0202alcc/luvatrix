from __future__ import annotations

import threading
import unittest

import torch

from luvatrix_core.core.window_matrix import (
    FullRewrite,
    Multiply,
    PushColumn,
    PushRow,
    ReplaceColumn,
    ReplaceRect,
    ReplaceRow,
    WriteBatch,
    WindowMatrix,
)


class WindowMatrixProtocolTests(unittest.TestCase):
    def test_init_uses_canonical_shape_dtype(self) -> None:
        matrix = WindowMatrix(height=3, width=4)
        snap = matrix.read_snapshot()
        self.assertEqual(tuple(snap.shape), (3, 4, 4))
        self.assertEqual(snap.dtype, torch.uint8)
        self.assertTrue(torch.all(snap[:, :, 3] == 255))
        self.assertEqual(matrix.pending_call_blit_count(), 0)

    def test_full_rewrite_emits_call_blit(self) -> None:
        matrix = WindowMatrix(height=2, width=2)
        payload = torch.tensor(
            [
                [[1, 2, 3, 4], [10, 11, 12, 13]],
                [[21, 22, 23, 24], [30, 31, 32, 33]],
            ]
        )
        event = matrix.submit_write_batch(WriteBatch([FullRewrite(payload)]))
        self.assertEqual(event.revision, 1)
        self.assertEqual(matrix.pending_call_blit_count(), 1)
        self.assertIsNotNone(matrix.pop_call_blit())
        self.assertEqual(matrix.pending_call_blit_count(), 0)
        self.assertTrue(torch.equal(matrix.read_snapshot(), payload.to(torch.uint8)))

    def test_invalid_pixels_replaced_and_warned_once_per_batch(self) -> None:
        matrix = WindowMatrix(height=2, width=2)
        invalid_full = torch.tensor(
            [
                [[300, 0, 0, 255], [1, 2, 3, 4]],
                [[5, 6, 7, 8], [9, 10, -1, 12]],
            ],
            dtype=torch.int32,
        )
        invalid_col = torch.tensor(
            [
                [1, 2, 3, 4],
                [999, 0, 0, 255],
            ],
            dtype=torch.int32,
        )
        with self.assertLogs("luvatrix_core.core.window_matrix", level="WARNING") as logs:
            matrix.submit_write_batch(
                WriteBatch(
                    [
                        FullRewrite(invalid_full),
                        ReplaceColumn(index=0, column_h_4=invalid_col),
                    ]
                )
            )
        self.assertEqual(len(logs.output), 1)
        self.assertIn("offending_pixels=3", logs.output[0])
        snap = matrix.read_snapshot()
        magenta = torch.tensor([255, 0, 255, 255], dtype=torch.uint8)
        # [0,0] was sanitized in full_rewrite, then overwritten by replace_column.
        self.assertFalse(torch.equal(snap[0, 0], magenta))
        self.assertTrue(torch.equal(snap[1, 0], magenta))
        self.assertTrue(torch.equal(snap[1, 1], magenta))

    def test_push_column_shifts_and_evicts(self) -> None:
        matrix = WindowMatrix(height=1, width=4)
        base = torch.tensor([[[1, 0, 0, 255], [2, 0, 0, 255], [3, 0, 0, 255], [4, 0, 0, 255]]])
        matrix.submit_write_batch(WriteBatch([FullRewrite(base)]))
        pushed = torch.tensor([[9, 0, 0, 255]])
        matrix.submit_write_batch(WriteBatch([PushColumn(index=1, column_h_4=pushed)]))
        snap = matrix.read_snapshot()
        got = snap[0, :, 0].tolist()
        self.assertEqual(got, [1, 9, 2, 3])

    def test_push_row_shifts_and_evicts(self) -> None:
        matrix = WindowMatrix(height=4, width=1)
        base = torch.tensor(
            [[[1, 0, 0, 255]], [[2, 0, 0, 255]], [[3, 0, 0, 255]], [[4, 0, 0, 255]]]
        )
        matrix.submit_write_batch(WriteBatch([FullRewrite(base)]))
        pushed = torch.tensor([[9, 0, 0, 255]])
        matrix.submit_write_batch(WriteBatch([PushRow(index=2, row_w_4=pushed)]))
        snap = matrix.read_snapshot()
        got = snap[:, 0, 0].tolist()
        self.assertEqual(got, [1, 2, 9, 3])

    def test_replace_row_and_column(self) -> None:
        matrix = WindowMatrix(height=2, width=2)
        base = torch.zeros((2, 2, 4), dtype=torch.uint8)
        matrix.submit_write_batch(WriteBatch([FullRewrite(base)]))
        matrix.submit_write_batch(
            WriteBatch(
                [
                    ReplaceRow(index=1, row_w_4=torch.tensor([[5, 0, 0, 255], [6, 0, 0, 255]])),
                    ReplaceColumn(index=0, column_h_4=torch.tensor([[7, 0, 0, 255], [8, 0, 0, 255]])),
                ]
            )
        )
        snap = matrix.read_snapshot()
        self.assertEqual(snap[0, 0, 0].item(), 7)
        self.assertEqual(snap[1, 0, 0].item(), 8)
        self.assertEqual(snap[1, 1, 0].item(), 6)

    def test_replace_rect_updates_subregion(self) -> None:
        matrix = WindowMatrix(height=4, width=5)
        base = torch.zeros((4, 5, 4), dtype=torch.uint8)
        matrix.submit_write_batch(WriteBatch([FullRewrite(base)]))
        patch = torch.tensor(
            [
                [[10, 0, 0, 255], [11, 0, 0, 255]],
                [[12, 0, 0, 255], [13, 0, 0, 255]],
            ],
            dtype=torch.uint8,
        )
        matrix.submit_write_batch(
            WriteBatch([ReplaceRect(x=2, y=1, width=2, height=2, rect_h_w_4=patch)])
        )
        snap = matrix.read_snapshot()
        self.assertEqual(snap[1, 2, 0].item(), 10)
        self.assertEqual(snap[1, 3, 0].item(), 11)
        self.assertEqual(snap[2, 2, 0].item(), 12)
        self.assertEqual(snap[2, 3, 0].item(), 13)
        self.assertEqual(snap[0, 0, 0].item(), 0)

    def test_multiply_applies_transform_and_clamps(self) -> None:
        matrix = WindowMatrix(height=1, width=1)
        base = torch.tensor([[[200, 10, 10, 255]]], dtype=torch.uint8)
        matrix.submit_write_batch(WriteBatch([FullRewrite(base)]))
        # Double red channel, keep other channels.
        mul = torch.tensor(
            [
                [2.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        matrix.submit_write_batch(WriteBatch([Multiply(color_matrix_4x4=mul)]))
        snap = matrix.read_snapshot()
        self.assertEqual(snap[0, 0, 0].item(), 255)
        self.assertEqual(snap[0, 0, 1].item(), 10)
        self.assertEqual(snap[0, 0, 2].item(), 10)
        self.assertEqual(snap[0, 0, 3].item(), 255)

    def test_atomic_batch_rejects_invalid_without_mutation(self) -> None:
        matrix = WindowMatrix(height=2, width=2)
        base = torch.tensor(
            [
                [[1, 1, 1, 255], [2, 2, 2, 255]],
                [[3, 3, 3, 255], [4, 4, 4, 255]],
            ],
            dtype=torch.uint8,
        )
        matrix.submit_write_batch(WriteBatch([FullRewrite(base)]))
        before = matrix.read_snapshot()
        with self.assertRaises(ValueError):
            matrix.submit_write_batch(
                WriteBatch(
                    [
                        ReplaceColumn(index=1, column_h_4=torch.tensor([[9, 9, 9, 255], [8, 8, 8, 255]])),
                        ReplaceRow(index=0, row_w_4=torch.tensor([[1, 2, 3, 4]])),
                    ]
                )
            )
        after = matrix.read_snapshot()
        self.assertTrue(torch.equal(before, after))
        self.assertEqual(matrix.pending_call_blit_count(), 1)

    def test_single_writer_lock_serializes_commits(self) -> None:
        matrix = WindowMatrix(height=1, width=1)

        def do_commit(value: int) -> None:
            matrix.submit_write_batch(
                WriteBatch([FullRewrite(torch.tensor([[[value, 0, 0, 255]]], dtype=torch.uint8))])
            )

        threads = [threading.Thread(target=do_commit, args=(i,)) for i in range(1, 11)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(matrix.revision, 10)
        self.assertEqual(matrix.pending_call_blit_count(), 10)


if __name__ == "__main__":
    unittest.main()
