"""Text interfaces and components for Luvatrix UI."""

from importlib import import_module


_LAZY_EXPORTS = {
    "TextComponent": (".component", "TextComponent"),
    "FontSpec": (".renderer", "FontSpec"),
    "TextAppearance": (".renderer", "TextAppearance"),
    "TextLayoutMetrics": (".renderer", "TextLayoutMetrics"),
    "TextMeasureRequest": (".renderer", "TextMeasureRequest"),
    "TextRenderBatch": (".renderer", "TextRenderBatch"),
    "TextRenderCommand": (".renderer", "TextRenderCommand"),
    "TextRenderer": (".renderer", "TextRenderer"),
    "TextSizeSpec": (".renderer", "TextSizeSpec"),
    "PreparedText": (".wrapping", "PreparedText"),
    "TextLayout": (".wrapping", "TextLayout"),
    "TextWrapping": (".wrapping", "TextWrapping"),
    "WrappedLine": (".wrapping", "WrappedLine"),
    "layout_text": (".wrapping", "layout_text"),
    "prepare_text": (".wrapping", "prepare_text"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_EXPORTS.keys())
