"""iOS Keychain bridge for secure token storage.

The Swift side of the native scaffold (`Luvatrix/KeychainBridge.swift`) owns
the SecItem* calls (SecItemAdd/SecItemCopyMatching/SecItemUpdate/SecItemDelete
with kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly). This module resolves
that ObjC class through rubicon-objc on first use and exposes the
read_secret/write_secret/delete_secret callables that
`luvatrix.auth.SecureWorkosTokenStore` expects. Linux tests substitute a fake
Swift object via ``IOSKeychain(bridge=...)``.
"""

from __future__ import annotations

import threading
from typing import Callable
from urllib.parse import urlparse


class IOSKeychainError(RuntimeError):
    """The native Keychain bridge is unavailable or rejected an operation."""


def keychain_account_for_instance(instance_url: str) -> str:
    """Derive a per-instance Keychain account so instances never collide."""
    parsed = urlparse(instance_url.strip())
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise ValueError(f"instance URL has no host: {instance_url!r}")
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = host if parsed.port in (None, default_port) else f"{host}:{parsed.port}"
    return f"workos.{netloc}"


class IOSKeychain:
    """String-secret store over the Swift `LuvatrixKeychain` ObjC class."""

    def __init__(
        self,
        *,
        bridge: object | None = None,
        resolver: Callable[[], object] | None = None,
    ) -> None:
        self._bridge = bridge
        self._resolver = resolver or _resolve_swift_keychain

    def read_secret(self, account: str) -> str | None:
        account = _require_account(account)
        value = self._bridge_obj().readSecret_(account)
        return None if value is None else str(value)

    def write_secret(self, account: str, value: str) -> None:
        account = _require_account(account)
        ok = self._bridge_obj().writeSecret_forAccount_(str(value), account)
        if not ok:
            raise IOSKeychainError(f"the iOS Keychain rejected the write for account {account!r}")

    def delete_secret(self, account: str) -> None:
        account = _require_account(account)
        self._bridge_obj().deleteSecret_(account)

    def _bridge_obj(self) -> object:
        if self._bridge is None:
            try:
                self._bridge = self._resolver()
            except Exception as exc:
                raise IOSKeychainError(
                    "the native iOS Keychain bridge is unavailable; run inside the "
                    "Luvatrix iOS scaffold (LuvatrixKeychain) so tokens land in the "
                    "device Keychain"
                ) from exc
        return self._bridge


def _resolve_swift_keychain() -> object:
    from rubicon.objc import ObjCClass

    return ObjCClass("LuvatrixKeychain")


def _require_account(account: str) -> str:
    if not account.strip():
        raise ValueError("keychain account is required")
    return account


_default_lock = threading.Lock()
_default_keychain = IOSKeychain()


def default_keychain() -> IOSKeychain:
    with _default_lock:
        return _default_keychain


def set_default_keychain(keychain: IOSKeychain) -> None:
    with _default_lock:
        global _default_keychain
        _default_keychain = keychain


def read_secret(account: str) -> str | None:
    return default_keychain().read_secret(account)


def write_secret(account: str, value: str) -> None:
    default_keychain().write_secret(account, value)


def delete_secret(account: str) -> None:
    default_keychain().delete_secret(account)


def secure_workos_token_store(
    instance_url: str,
    *,
    keychain: IOSKeychain | None = None,
):
    """A `SecureWorkosTokenStore` persisted in the iOS Keychain for one instance."""
    from luvatrix.auth import SecureWorkosTokenStore

    store = keychain if keychain is not None else default_keychain()
    return SecureWorkosTokenStore(
        read_secret=store.read_secret,
        write_secret=store.write_secret,
        delete_secret=store.delete_secret,
        key=keychain_account_for_instance(instance_url),
    )
