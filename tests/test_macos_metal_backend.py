from __future__ import annotations

import unittest

import torch

from luvatrix_core.perf.copy_telemetry import begin_copy_telemetry_frame, snapshot_copy_telemetry
from luvatrix_core.platform.macos.metal_backend import _upload_buffer


class MacOSMetalBackendUploadTests(unittest.TestCase):
    def test_upload_buffer_reuses_contiguous_cpu_tensor_storage(self) -> None:
        rgba = torch.zeros((2, 2, 4), dtype=torch.uint8)
        begin_copy_telemetry_frame()
        owner, upload = _upload_buffer(rgba)
        telemetry = snapshot_copy_telemetry()

        rgba[0, 0, 0] = 123
        self.assertIs(owner, upload)
        self.assertEqual(int(owner[0, 0, 0]), 123)
        self.assertEqual(telemetry["upload_pack_ns"], 0)

    def test_upload_buffer_packs_non_contiguous_tensor(self) -> None:
        rgba = torch.zeros((4, 2, 4), dtype=torch.uint8)[::2]
        self.assertFalse(rgba.is_contiguous())
        begin_copy_telemetry_frame()
        owner, upload = _upload_buffer(rgba)
        telemetry = snapshot_copy_telemetry()

        self.assertIs(owner, upload)
        self.assertEqual(owner.shape, (2, 2, 4))
        self.assertGreaterEqual(telemetry["upload_pack_ns"], 0)
        self.assertTrue(owner.flags.c_contiguous)


if __name__ == "__main__":
    unittest.main()
