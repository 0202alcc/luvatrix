from __future__ import annotations

import os
import threading
import time


_lock = threading.Lock()
_active = True
_last_transition_ns = time.time_ns()
_transition_count = 0


def set_app_active(active: bool) -> None:
    global _active, _last_transition_ns, _transition_count
    with _lock:
        next_active = bool(active)
        if _active != next_active:
            _transition_count += 1
            _last_transition_ns = time.time_ns()
        _active = next_active
    os.environ["LUVATRIX_IOS_APP_ACTIVE"] = "1" if active else "0"


def is_app_active() -> bool:
    with _lock:
        return bool(_active)


def snapshot() -> dict[str, int]:
    with _lock:
        return {
            "ios_app_active": int(_active),
            "ios_lifecycle_transition_count": int(_transition_count),
            "ios_lifecycle_last_transition_ns": int(_last_transition_ns),
        }
