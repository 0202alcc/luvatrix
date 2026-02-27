import unittest

from luvatrix_ui.style.theme import DEFAULT_TOKENS, validate_theme_tokens


class ThemeTokensTests(unittest.TestCase):
    def test_validate_theme_defaults(self) -> None:
        tokens = validate_theme_tokens()
        self.assertEqual(tokens, DEFAULT_TOKENS)

    def test_validate_theme_accepts_partial_override(self) -> None:
        tokens = validate_theme_tokens({"button_bg_hover": "#112233", "font_size_px": 16})
        self.assertEqual(tokens.button_bg_hover, "#112233")
        self.assertEqual(tokens.font_size_px, 16.0)
        self.assertEqual(tokens.button_bg_idle, DEFAULT_TOKENS.button_bg_idle)

    def test_validate_theme_rejects_unknown_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown theme token"):
            validate_theme_tokens({"unknown": "#112233"})

    def test_validate_theme_rejects_invalid_hex_color(self) -> None:
        with self.assertRaisesRegex(ValueError, "hex color"):
            validate_theme_tokens({"button_text": "red"})

    def test_validate_theme_rejects_non_positive_font_size(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive number"):
            validate_theme_tokens({"font_size_px": 0})


if __name__ == "__main__":
    unittest.main()
