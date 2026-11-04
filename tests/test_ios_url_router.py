from __future__ import annotations

import unittest

from luvatrix_core.platform.ios import url_router
from luvatrix_core.platform.ios.url_router import UrlRouter


class UrlRouterTests(unittest.TestCase):
    def test_open_url_without_handler_is_buffered(self) -> None:
        router = UrlRouter()

        self.assertFalse(router.handle_open_url("ainomic://auth/callback?code=abc"))
        self.assertEqual(router.buffered(), ("ainomic://auth/callback?code=abc",))

    def test_registration_drains_matching_buffered_urls(self) -> None:
        router = UrlRouter()
        router.handle_open_url("ainomic://auth/callback?code=abc")
        router.handle_open_url("luvatrix://other")

        seen: list[str] = []
        router.register("ainomic", lambda url: seen.append(url) or True)

        self.assertEqual(seen, ["ainomic://auth/callback?code=abc"])
        self.assertEqual(router.buffered(), ("luvatrix://other",))

    def test_registered_handler_receives_urls_immediately(self) -> None:
        router = UrlRouter()
        seen: list[str] = []
        router.register("ainomic", lambda url: seen.append(url) or True)

        self.assertTrue(router.handle_open_url("ainomic://auth/callback?code=abc&state=s"))
        self.assertEqual(seen, ["ainomic://auth/callback?code=abc&state=s"])
        self.assertEqual(router.buffered(), ())

    def test_declined_url_is_not_consumed_or_buffered(self) -> None:
        router = UrlRouter()
        router.register("ainomic", lambda url: False)

        self.assertFalse(router.handle_open_url("ainomic://unexpected"))
        self.assertEqual(router.buffered(), ())

    def test_scheme_match_is_case_insensitive(self) -> None:
        router = UrlRouter()
        seen: list[str] = []
        router.register("ainomic", lambda url: seen.append(url) or True)

        self.assertTrue(router.handle_open_url("AINOMIC://auth/callback?code=abc"))
        self.assertEqual(len(seen), 1)

    def test_unregister_stops_delivery(self) -> None:
        router = UrlRouter()
        seen: list[str] = []
        router.register("ainomic", lambda url: seen.append(url) or True)
        router.unregister("ainomic")

        self.assertFalse(router.handle_open_url("ainomic://auth/callback?code=abc"))
        self.assertEqual(seen, [])
        self.assertEqual(len(router.buffered()), 1)

    def test_handler_exception_does_not_break_router(self) -> None:
        router = UrlRouter()

        def broken(url: str) -> bool:
            raise RuntimeError("boom")

        router.register("ainomic", broken)
        self.assertFalse(router.handle_open_url("ainomic://auth/callback?code=abc"))

    def test_buffer_is_bounded(self) -> None:
        router = UrlRouter(max_buffered=2)
        for index in range(4):
            router.handle_open_url(f"ainomic://auth/callback?code={index}")

        self.assertEqual(
            router.buffered(),
            ("ainomic://auth/callback?code=2", "ainomic://auth/callback?code=3"),
        )

    def test_module_level_delegates_to_default_router(self) -> None:
        seen: list[str] = []
        url_router.register_scheme("ainomic-test", lambda url: seen.append(url) or True)
        try:
            self.assertTrue(url_router.handle_open_url("ainomic-test://x"))
            self.assertEqual(seen, ["ainomic-test://x"])
        finally:
            url_router.unregister_scheme("ainomic-test")


if __name__ == "__main__":
    unittest.main()
