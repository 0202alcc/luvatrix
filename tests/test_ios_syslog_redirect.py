from __future__ import annotations

import sys
from unittest.mock import patch

from luvatrix_core.platform.ios import runner


class _FakeSyslog:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args) -> None:
        self.calls.append(args)


class _FakeLibc:
    def __init__(self) -> None:
        self.syslog = _FakeSyslog()


def test_redirected_lines_reach_syslog_without_variadic_arguments() -> None:
    # syslog is variadic; on Apple arm64 ctypes cannot pass variadic arguments, so the
    # message has to be the (escaped) format string itself.
    libc = _FakeLibc()
    saved = sys.stdout, sys.stderr
    try:
        with patch("ctypes.CDLL", return_value=libc), patch.dict("os.environ", {"LUVATRIX_MAC_LOG_IP": ""}):
            runner._setup_syslog_redirect()
            print("[figma-tour] 50% done")
            sys.stderr.write("tail without newline")
            sys.stderr.flush()
    finally:
        sys.stdout, sys.stderr = saved

    assert libc.syslog.calls == [(5, b"[figma-tour] 50%% done"), (5, b"tail without newline")]
    assert len(libc.syslog.argtypes) == 2
