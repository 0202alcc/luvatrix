"""Single-thread background job runner. Stub module — see tests."""
from __future__ import annotations


class Worker:
    def submit(self, label: str, fn) -> None: raise NotImplementedError
    def poll(self) -> list: raise NotImplementedError
    def shutdown(self) -> None: raise NotImplementedError
