from __future__ import annotations

import unittest

import pytest

from luvatrix.auth import WorkosToken
from luvatrix_core.platform.ios import keychain as ios_keychain
from luvatrix_core.platform.ios.keychain import (
    IOSKeychain,
    IOSKeychainError,
    keychain_account_for_instance,
    secure_workos_token_store,
)


class FakeSwiftKeychain:
    """Fake for the ObjC `LuvatrixKeychain` boundary on the Swift side.

    Method names mirror the ObjC selectors (`readSecret:`, `writeSecret:forAccount:`,
    `deleteSecret:`) exactly as rubicon-objc surfaces them to Python.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.calls: list[tuple[str, ...]] = []
        self.write_ok = True

    def readSecret_(self, account: str) -> str | None:
        self.calls.append(("read", account))
        return self.values.get(account)

    def writeSecret_forAccount_(self, value: str, account: str) -> bool:
        self.calls.append(("write", account, value))
        if not self.write_ok:
            return False
        self.values[account] = value
        return True

    def deleteSecret_(self, account: str) -> bool:
        self.calls.append(("delete", account))
        self.values.pop(account, None)
        return True


class IOSKeychainTests(unittest.TestCase):
    def test_read_missing_returns_none(self) -> None:
        store = IOSKeychain(bridge=FakeSwiftKeychain())
        self.assertIsNone(store.read_secret("workos.app.nomic.ai"))

    def test_write_then_read_round_trip(self) -> None:
        bridge = FakeSwiftKeychain()
        store = IOSKeychain(bridge=bridge)

        store.write_secret("acct", "secret-1")

        self.assertEqual(store.read_secret("acct"), "secret-1")
        self.assertEqual(bridge.calls, [("write", "acct", "secret-1"), ("read", "acct")])

    def test_write_overwrites_existing_value(self) -> None:
        store = IOSKeychain(bridge=FakeSwiftKeychain())
        store.write_secret("acct", "one")
        store.write_secret("acct", "two")
        self.assertEqual(store.read_secret("acct"), "two")

    def test_failed_write_raises(self) -> None:
        bridge = FakeSwiftKeychain()
        bridge.write_ok = False
        store = IOSKeychain(bridge=bridge)

        with pytest.raises(IOSKeychainError):
            store.write_secret("acct", "secret")

    def test_delete_removes_value(self) -> None:
        store = IOSKeychain(bridge=FakeSwiftKeychain())
        store.write_secret("acct", "secret")
        store.delete_secret("acct")
        self.assertIsNone(store.read_secret("acct"))

    def test_blank_account_rejected(self) -> None:
        store = IOSKeychain(bridge=FakeSwiftKeychain())
        with pytest.raises(ValueError):
            store.read_secret("  ")
        with pytest.raises(ValueError):
            store.write_secret("", "secret")
        with pytest.raises(ValueError):
            store.delete_secret("")

    def test_missing_native_bridge_is_actionable_error(self) -> None:
        def resolver() -> object:
            raise ImportError("No module named 'rubicon'")

        store = IOSKeychain(resolver=resolver)
        with pytest.raises(IOSKeychainError, match="Keychain"):
            store.read_secret("acct")

    def test_module_level_secret_callables_use_default_keychain(self) -> None:
        bridge = FakeSwiftKeychain()
        previous = ios_keychain.default_keychain()
        ios_keychain.set_default_keychain(IOSKeychain(bridge=bridge))
        try:
            ios_keychain.write_secret("acct", "v1")
            self.assertEqual(ios_keychain.read_secret("acct"), "v1")
            ios_keychain.delete_secret("acct")
            self.assertIsNone(ios_keychain.read_secret("acct"))
        finally:
            ios_keychain.set_default_keychain(previous)


class KeychainAccountTests(unittest.TestCase):
    def test_https_default_port_is_dropped(self) -> None:
        self.assertEqual(keychain_account_for_instance("https://app.nomic.ai"), "workos.app.nomic.ai")
        self.assertEqual(keychain_account_for_instance("https://app.nomic.ai:443"), "workos.app.nomic.ai")

    def test_non_default_port_is_kept(self) -> None:
        self.assertEqual(keychain_account_for_instance("http://localhost:3000"), "workos.localhost:3000")
        self.assertEqual(keychain_account_for_instance("https://staging.nomic.ai:8443"), "workos.staging.nomic.ai:8443")

    def test_host_is_normalized(self) -> None:
        self.assertEqual(keychain_account_for_instance("  HTTPS://App.Nomic.AI/  "), "workos.app.nomic.ai")

    def test_distinct_instances_do_not_collide(self) -> None:
        self.assertNotEqual(
            keychain_account_for_instance("https://app.nomic.ai"),
            keychain_account_for_instance("https://demo.drive.nomic.ai"),
        )

    def test_missing_host_rejected(self) -> None:
        with pytest.raises(ValueError):
            keychain_account_for_instance("not a url")
        with pytest.raises(ValueError):
            keychain_account_for_instance("")


class SecureWorkosTokenStoreFactoryTests(unittest.TestCase):
    def test_round_trip_through_fake_swift_side(self) -> None:
        bridge = FakeSwiftKeychain()
        store = secure_workos_token_store(
            "https://app.nomic.ai",
            keychain=IOSKeychain(bridge=bridge),
        )

        self.assertIsNone(store.load())
        token = WorkosToken(
            access_token="a",
            token_type="Bearer",
            expires_at=123.0,
            refresh_token="r",
            scope="openid",
        )
        store.save(token)
        self.assertEqual(store.load(), token)
        store.clear()
        self.assertIsNone(store.load())

        write_accounts = [call[1] for call in bridge.calls if call[0] == "write"]
        self.assertEqual(write_accounts, ["workos.app.nomic.ai"])

    def test_tokens_for_two_instances_stay_separate(self) -> None:
        keychain = IOSKeychain(bridge=FakeSwiftKeychain())
        prod = secure_workos_token_store("https://app.nomic.ai", keychain=keychain)
        local = secure_workos_token_store("http://localhost:3000", keychain=keychain)

        token = WorkosToken(access_token="local", token_type="Bearer", expires_at=1.0)
        local.save(token)

        self.assertEqual(local.load(), token)
        self.assertIsNone(prod.load())


if __name__ == "__main__":
    unittest.main()
