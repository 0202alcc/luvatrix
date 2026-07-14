"""First-party UI contracts and components for Luvatrix."""

from importlib import import_module


_LAZY_EXPORTS = {
    "BoundingBox": (".component_schema", "BoundingBox"),
    "ComponentBase": (".component_schema", "ComponentBase"),
    "CoordinatePoint": (".component_schema", "CoordinatePoint"),
    "CoordinateTransformer": (".component_schema", "CoordinateTransformer"),
    "DisplayableArea": (".component_schema", "DisplayableArea"),
    "parse_coordinate_notation": (".component_schema", "parse_coordinate_notation"),
    "ButtonModel": (".controls.button", "ButtonModel"),
    "ButtonState": (".controls.button", "ButtonState"),
    "HDIPressEvent": (".controls.interaction", "HDIPressEvent"),
    "PressPhase": (".controls.interaction", "PressPhase"),
    "parse_hdi_press_event": (".controls.interaction", "parse_hdi_press_event"),
    "StainedGlassButtonComponent": (".controls.stained_glass_button", "StainedGlassButtonComponent"),
    "StainedGlassButtonRenderBatch": (
        ".controls.stained_glass_button",
        "StainedGlassButtonRenderBatch",
    ),
    "StainedGlassButtonRenderCommand": (
        ".controls.stained_glass_button",
        "StainedGlassButtonRenderCommand",
    ),
    "StainedGlassButtonRenderer": (".controls.stained_glass_button", "StainedGlassButtonRenderer"),
    "SVGComponent": (".controls.svg_component", "SVGComponent"),
    "SVGRenderBatch": (".controls.svg_renderer", "SVGRenderBatch"),
    "SVGRenderCommand": (".controls.svg_renderer", "SVGRenderCommand"),
    "SVGRenderer": (".controls.svg_renderer", "SVGRenderer"),
    "AgileRenderConfig": (".planning", "AgileRenderConfig"),
    "AgileTaskCard": (".planning", "AgileTaskCard"),
    "GanttRenderConfig": (".planning", "GanttRenderConfig"),
    "PlanningExportBundle": (".planning", "PlanningExportBundle"),
    "PlanningInteractionState": (".planning", "PlanningInteractionState"),
    "PlanningTimeline": (".planning", "PlanningTimeline"),
    "TimelineMilestone": (".planning", "TimelineMilestone"),
    "ValidationReport": (".planning", "ValidationReport"),
    "attach_dependency_defaults": (".planning", "attach_dependency_defaults"),
    "apply_task_filters": (".planning", "apply_task_filters"),
    "apply_week_viewport": (".planning", "apply_week_viewport"),
    "build_discord_payload": (".planning", "build_discord_payload"),
    "build_m011_task_cards": (".planning", "build_m011_task_cards"),
    "clamp_week_window": (".planning", "clamp_week_window"),
    "export_planning_bundle": (".planning", "export_planning_bundle"),
    "load_timeline_model": (".planning", "load_timeline_model"),
    "milestone_clickthrough_map": (".planning", "milestone_clickthrough_map"),
    "pan_week_window": (".planning", "pan_week_window"),
    "planning_timeline_schema": (".planning", "planning_timeline_schema"),
    "render_agile_board_ascii": (".planning", "render_agile_board_ascii"),
    "render_agile_board_markdown": (".planning", "render_agile_board_markdown"),
    "render_gantt_ascii": (".planning", "render_gantt_ascii"),
    "require_valid_planning_suite": (".planning", "require_valid_planning_suite"),
    "timeline_from_dict": (".planning", "timeline_from_dict"),
    "validate_dependency_integrity": (".planning", "validate_dependency_integrity"),
    "validate_planning_suite": (".planning", "validate_planning_suite"),
    "validate_render_consistency": (".planning", "validate_render_consistency"),
    "zoom_week_window": (".planning", "zoom_week_window"),
    "ThemeTokens": (".style.theme", "ThemeTokens"),
    "validate_theme_tokens": (".style.theme", "validate_theme_tokens"),
    "TableColumn": (".table", "TableColumn"),
    "TableComponent": (".table", "TableComponent"),
    "TableRenderStyle": (".table", "TableRenderStyle"),
    "TableState": (".table", "TableState"),
    "TextComponent": (".text.component", "TextComponent"),
    "FontSpec": (".text.renderer", "FontSpec"),
    "TextAppearance": (".text.renderer", "TextAppearance"),
    "TextLayoutMetrics": (".text.renderer", "TextLayoutMetrics"),
    "TextMeasureRequest": (".text.renderer", "TextMeasureRequest"),
    "TextRenderBatch": (".text.renderer", "TextRenderBatch"),
    "TextRenderCommand": (".text.renderer", "TextRenderCommand"),
    "TextRenderer": (".text.renderer", "TextRenderer"),
    "TextSizeSpec": (".text.renderer", "TextSizeSpec"),
    "ComponentSemantics": (".ui_ir", "ComponentSemantics"),
    "ComponentTransform": (".ui_ir", "ComponentTransform"),
    "CoordinateFrameSpec": (".ui_ir", "CoordinateFrameSpec"),
    "Insets": (".ui_ir", "Insets"),
    "InteractionBinding": (".ui_ir", "InteractionBinding"),
    "MatrixSpec": (".ui_ir", "MatrixSpec"),
    "UIIRAsset": (".ui_ir", "UIIRAsset"),
    "UIIRComponent": (".ui_ir", "UIIRComponent"),
    "UIIRPage": (".ui_ir", "UIIRPage"),
    "default_ui_ir_page_schema": (".ui_ir", "default_ui_ir_page_schema"),
    "validate_ui_ir_payload": (".ui_ir", "validate_ui_ir_payload"),
    "SUPPORTED_HDI_HOOKS": (".planes_protocol", "SUPPORTED_HDI_HOOKS"),
    "PlanesAppMetadata": (".planes_protocol", "PlanesAppMetadata"),
    "PlanesValidationError": (".planes_protocol", "PlanesValidationError"),
    "compile_planes_to_ui_ir": (".planes_protocol", "compile_planes_to_ui_ir"),
    "resolve_web_metadata": (".planes_protocol", "resolve_web_metadata"),
    "validate_planes_payload": (".planes_protocol", "validate_planes_payload"),
    "EventHandler": (".planes_runtime", "EventHandler"),
    "PlaneApp": (".planes_runtime", "PlaneApp"),
    "load_plane_app": (".planes_runtime", "load_plane_app"),
}

_OPTIONAL_EXPORTS = {
    name
    for name, (module_name, _) in _LAZY_EXPORTS.items()
    if module_name.startswith((".planning", ".style", ".table", ".ui_ir", ".planes"))
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    try:
        value = getattr(import_module(module_name, __name__), attribute_name)
    except ImportError:
        if name not in _OPTIONAL_EXPORTS:
            raise
        value = None
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LAZY_EXPORTS.keys())
