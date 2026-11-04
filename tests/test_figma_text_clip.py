"""TEXT nodes must truncate at their clip boundary instead of mid-glyph cuts."""

from __future__ import annotations

from luvatrix_ui.figma.text import _Piece, _Style, truncate_pieces_to_width

_STYLE = _Style(
    family="Inter",
    weight=400,
    italic=False,
    size=14,
    letter_spacing=0,
    line_height=18,
    paragraph_spacing=0,
    decoration="NONE",
    fills_key="{}",
    fills=(),
)

_ELLIPSIS = _Piece("…", _STYLE, 12.0)


def _piece(text: str, width: float) -> _Piece:
    return _Piece(text, _STYLE, width)


def test_truncation_ends_with_an_ellipsis_inside_the_available_width() -> None:
    pieces = [_piece("Riverfront ", 80.0), _piece("Tower ", 40.0), _piece("Level 3 ", 50.0)]

    result = truncate_pieces_to_width(pieces, 120.0, _ELLIPSIS)

    assert result, "truncation should keep at least the ellipsis"
    assert result[-1] is _ELLIPSIS
    assert sum(p.width for p in result) <= 120.0 + 1e-6
    # No partial piece: the kept pieces are whole ones from the original run.
    assert [p.width for p in result[:-1]] == [80.0]


def test_truncation_is_identity_when_the_line_fits() -> None:
    pieces = [_piece("Site Photos", 60.0)]

    assert truncate_pieces_to_width(pieces, 120.0, _ELLIPSIS) == pieces


def test_truncation_drops_whole_pieces_until_the_ellipsis_fits() -> None:
    pieces = [_piece("AAAA ", 30.0), _piece("BBBB ", 30.0), _piece("CCCC ", 30.0), _piece("DDDD", 30.0)]

    result = truncate_pieces_to_width(pieces, 95.0, _ELLIPSIS)

    assert result[-1] is _ELLIPSIS
    assert sum(p.width for p in result) <= 95.0 + 1e-6
    assert len(result) == 3


def test_truncation_of_an_empty_line_stays_empty() -> None:
    assert truncate_pieces_to_width([], 50.0, _ELLIPSIS) == []


def test_truncation_returns_empty_when_even_the_ellipsis_does_not_fit() -> None:
    assert truncate_pieces_to_width([_piece("wide ", 60.0)], 5.0, _ELLIPSIS) == []