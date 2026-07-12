from __future__ import annotations

import pytest

from luvatrix_ui.text.wrapping import TextWrapping, layout_text, prepare_text


def _measure(text: str) -> float:
    return float(len(text) * 10)


def test_normal_wrapping_collapses_whitespace_and_wraps_at_words() -> None:
    prepared = prepare_text("hello   world\nagain", measure=_measure)

    layout = layout_text(prepared, max_width_px=60, line_height_px=14)

    assert [line.text for line in layout.lines] == ["hello", "world", "again"]
    assert layout.line_count == 3
    assert layout.height_px == 42


def test_pre_wrap_preserves_hard_breaks_and_spaces() -> None:
    prepared = prepare_text(
        "A  B\nC",
        measure=_measure,
        wrapping=TextWrapping(white_space="pre-wrap"),
    )

    layout = layout_text(prepared, max_width_px=100, line_height_px=12)

    assert [line.text for line in layout.lines] == ["A  B", "C"]


def test_pre_wrap_preserves_empty_line_after_trailing_newline() -> None:
    prepared = prepare_text(
        "A\n",
        measure=_measure,
        wrapping=TextWrapping(white_space="pre-wrap"),
    )

    layout = layout_text(prepared, max_width_px=100, line_height_px=12)

    assert [line.text for line in layout.lines] == ["A", ""]


def test_overlong_word_breaks_without_splitting_emoji_grapheme() -> None:
    family = "👨‍👩‍👧‍👦"
    prepared = prepare_text(f"{family}X", measure=lambda text: 10.0 if text == family else float(len(text) * 10))

    layout = layout_text(prepared, max_width_px=10, line_height_px=12)

    assert [line.text for line in layout.lines] == [family, "X"]


def test_prepared_text_reuses_measurements_across_widths() -> None:
    calls: list[str] = []

    def measure(text: str) -> float:
        calls.append(text)
        return float(len(text) * 10)

    prepared = prepare_text("one two three", measure=measure)
    calls_after_prepare = list(calls)

    layout_text(prepared, max_width_px=50, line_height_px=12)
    layout_text(prepared, max_width_px=100, line_height_px=12)

    assert calls == calls_after_prepare


def test_preparation_uses_shaped_token_width_for_normal_layout() -> None:
    def measure(text: str) -> float:
        return 15.0 if text == "AV" else float(len(text) * 10)

    prepared = prepare_text("AV", measure=measure)

    layout = layout_text(prepared, max_width_px=15, line_height_px=12)

    assert prepared.natural_width_px == 15.0
    assert [line.text for line in layout.lines] == ["AV"]


def test_wrapping_rejects_non_finite_measurements_and_constraints() -> None:
    with pytest.raises(ValueError, match="finite"):
        prepare_text("bad", measure=lambda _text: float("nan"))

    prepared = prepare_text("ok", measure=_measure)
    with pytest.raises(ValueError, match="finite"):
        layout_text(prepared, max_width_px=float("nan"), line_height_px=12)
