from __future__ import annotations

import unittest

from luvatrix_core.core.protocol_governance import check_protocol_compatibility


class ProtocolGovernanceTests(unittest.TestCase):
    def test_supported_protocol_is_accepted(self) -> None:
        result = check_protocol_compatibility("1")
        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.warning)

    def test_supported_v2_protocol_is_accepted_without_warning(self) -> None:
        result = check_protocol_compatibility("2")
        self.assertTrue(result.accepted)
        self.assertIsNone(result.warning)

    def test_unsupported_protocol_is_rejected(self) -> None:
        result = check_protocol_compatibility("999")
        self.assertFalse(result.accepted)

    def test_min_runtime_bound_is_enforced(self) -> None:
        result = check_protocol_compatibility("1", min_runtime_version="3")
        self.assertFalse(result.accepted)

    def test_max_runtime_bound_is_enforced(self) -> None:
        result = check_protocol_compatibility("1", max_runtime_version="0")
        self.assertFalse(result.accepted)


if __name__ == "__main__":
    unittest.main()
