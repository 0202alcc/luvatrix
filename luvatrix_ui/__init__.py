"""First-party UI contracts and components for Luvatrix."""

from .component_schema import (
    BoundingBox,
    ComponentBase,
    CoordinatePoint,
    CoordinateTransformer,
    DisplayableArea,
    parse_coordinate_notation,
)
from .controls.button import ButtonModel, ButtonState
from .controls.interaction import HDIPressEvent, PressPhase, parse_hdi_press_event
from .controls.stained_glass_button import (
    StainedGlassButtonComponent,
    StainedGlassButtonRenderBatch,
    StainedGlassButtonRenderCommand,
    StainedGlassButtonRenderer,
)
from .controls.svg_component import SVGComponent
from .controls.svg_renderer import SVGRenderBatch, SVGRenderCommand, SVGRenderer
try:
    from .planning import (
        AgileRenderConfig,
        AgileTaskCard,
        GanttRenderConfig,
        PlanningExportBundle,
        PlanningInteractionState,
        PlanningTimeline,
        TimelineMilestone,
        ValidationReport,
        attach_dependency_defaults,
        apply_task_filters,
        apply_week_viewport,
        build_discord_payload,
        build_m011_task_cards,
        clamp_week_window,
        export_planning_bundle,
        load_timeline_model,
        milestone_clickthrough_map,
        pan_week_window,
        planning_timeline_schema,
        render_agile_board_ascii,
        render_agile_board_markdown,
        render_gantt_ascii,
        require_valid_planning_suite,
        timeline_from_dict,
        validate_dependency_integrity,
        validate_planning_suite,
        validate_render_consistency,
        zoom_week_window,
    )
except ImportError:
    AgileRenderConfig = AgileTaskCard = GanttRenderConfig = PlanningExportBundle = None
    PlanningInteractionState = PlanningTimeline = TimelineMilestone = ValidationReport = None
    attach_dependency_defaults = apply_task_filters = apply_week_viewport = None
    build_discord_payload = build_m011_task_cards = clamp_week_window = None
    export_planning_bundle = load_timeline_model = milestone_clickthrough_map = None
    pan_week_window = planning_timeline_schema = render_agile_board_ascii = None
    render_agile_board_markdown = render_gantt_ascii = require_valid_planning_suite = None
    timeline_from_dict = validate_dependency_integrity = validate_planning_suite = None
    validate_render_consistency = zoom_week_window = None
try:
    from .style.theme import ThemeTokens, validate_theme_tokens
except ImportError:
    ThemeTokens = None
    validate_theme_tokens = None
try:
    from .table import TableColumn, TableComponent, TableState
except ImportError:
    TableColumn = TableComponent = TableState = None
from .text.component import TextComponent
from .text.renderer import (
    FontSpec,
    TextAppearance,
    TextLayoutMetrics,
    TextMeasureRequest,
    TextRenderBatch,
    TextRenderCommand,
    TextRenderer,
    TextSizeSpec,
)
try:
    from .ui_ir import (
        ComponentSemantics,
        ComponentTransform,
        CoordinateFrameSpec,
        Insets,
        InteractionBinding,
        MatrixSpec,
        UIIRAsset,
        UIIRComponent,
        UIIRPage,
        default_ui_ir_page_schema,
        validate_ui_ir_payload,
    )
except ImportError:
    ComponentSemantics = ComponentTransform = CoordinateFrameSpec = Insets = None
    InteractionBinding = MatrixSpec = UIIRAsset = UIIRComponent = UIIRPage = None
    default_ui_ir_page_schema = validate_ui_ir_payload = None
try:
    from .planes_protocol import (
        SUPPORTED_HDI_HOOKS,
        PlanesAppMetadata,
        PlanesValidationError,
        compile_planes_to_ui_ir,
        resolve_web_metadata,
        validate_planes_payload,
    )
except ImportError:
    SUPPORTED_HDI_HOOKS = None
    PlanesAppMetadata = PlanesValidationError = None
    compile_planes_to_ui_ir = resolve_web_metadata = validate_planes_payload = None
try:
    from .planes_runtime import (
        EventHandler,
        PlaneApp,
        load_plane_app,
    )
except ImportError:
    EventHandler = PlaneApp = load_plane_app = None

__all__ = [
    "BoundingBox",
    "AgileRenderConfig",
    "AgileTaskCard",
    "ButtonModel",
    "ButtonState",
    "ComponentBase",
    "CoordinatePoint",
    "CoordinateTransformer",
    "DisplayableArea",
    "FontSpec",
    "GanttRenderConfig",
    "HDIPressEvent",
    "PlanningExportBundle",
    "PlanningInteractionState",
    "PlanningTimeline",
    "PressPhase",
    "StainedGlassButtonComponent",
    "StainedGlassButtonRenderBatch",
    "StainedGlassButtonRenderCommand",
    "StainedGlassButtonRenderer",
    "SVGComponent",
    "SVGRenderBatch",
    "SVGRenderCommand",
    "SVGRenderer",
    "TextAppearance",
    "TableColumn",
    "TableComponent",
    "TableState",
    "TextComponent",
    "TextLayoutMetrics",
    "TextMeasureRequest",
    "TextRenderBatch",
    "TextRenderCommand",
    "TextRenderer",
    "TextSizeSpec",
    "ThemeTokens",
    "TimelineMilestone",
    "ValidationReport",
    "UIIRAsset",
    "UIIRComponent",
    "UIIRPage",
    "ComponentSemantics",
    "ComponentTransform",
    "CoordinateFrameSpec",
    "InteractionBinding",
    "Insets",
    "MatrixSpec",
    "attach_dependency_defaults",
    "apply_task_filters",
    "apply_week_viewport",
    "build_discord_payload",
    "build_m011_task_cards",
    "clamp_week_window",
    "default_ui_ir_page_schema",
    "export_planning_bundle",
    "load_timeline_model",
    "milestone_clickthrough_map",
    "pan_week_window",
    "planning_timeline_schema",
    "parse_coordinate_notation",
    "parse_hdi_press_event",
    "render_agile_board_ascii",
    "render_agile_board_markdown",
    "render_gantt_ascii",
    "require_valid_planning_suite",
    "timeline_from_dict",
    "validate_dependency_integrity",
    "validate_planning_suite",
    "validate_render_consistency",
    "validate_ui_ir_payload",
    "validate_theme_tokens",
    "zoom_week_window",
    "SUPPORTED_HDI_HOOKS",
    "PlanesAppMetadata",
    "PlanesValidationError",
    "compile_planes_to_ui_ir",
    "resolve_web_metadata",
    "validate_planes_payload",
    "EventHandler",
    "PlaneApp",
    "load_plane_app",
]
