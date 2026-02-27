from __future__ import annotations

import unittest

from luvatrix_ui.ui_ir import (
    CoordinateRef,
    InteractionBinding,
    MatrixSpec,
    UIIRComponent,
    UIIRPage,
    default_ui_ir_page_schema,
    validate_ui_ir_payload,
)


class UIIRTests(unittest.TestCase):
    def test_page_round_trip_and_ordering(self) -> None:
        page = UIIRPage(
            ir_version="0.1.0",
            app_protocol_version="1.0.0",
            page_id="home",
            matrix=MatrixSpec(width=640, height=360),
            aspect_mode="preserve",
            default_frame="cartesian_bl",
            components=(
                UIIRComponent(
                    component_id="a",
                    component_type="text",
                    position=CoordinateRef(x=10, y=20, frame="cartesian_bl"),
                    width=120,
                    height=30,
                    z_index=5,
                    interactions=(InteractionBinding(event="on_press", handler="open_a"),),
                ),
                UIIRComponent(
                    component_id="b",
                    component_type="svg",
                    position=CoordinateRef(x=5, y=10, frame="cartesian_bl"),
                    width=80,
                    height=80,
                    z_index=1,
                ),
            ),
        )

        payload = page.to_dict()
        parsed = UIIRPage.from_dict(payload)

        self.assertEqual(parsed.page_id, "home")
        draw_ids = [component.component_id for component in parsed.ordered_components_for_draw()]
        hit_ids = [component.component_id for component in parsed.ordered_components_for_hit_test()]
        self.assertEqual(draw_ids, ["b", "a"])
        self.assertEqual(hit_ids, ["a", "b"])

    def test_component_bounds_defaults_to_position_size(self) -> None:
        component = UIIRComponent(
            component_id="x",
            component_type="text",
            position=CoordinateRef(x=4, y=9, frame=None),
            width=50,
            height=10,
        )
        visual = component.resolved_visual_bounds("screen_tl")
        interaction = component.resolved_interaction_bounds("screen_tl")
        self.assertEqual((visual.x, visual.y, visual.width, visual.height, visual.frame), (4, 9, 50, 10, "screen_tl"))
        self.assertEqual((interaction.x, interaction.y, interaction.width, interaction.height, interaction.frame), (4, 9, 50, 10, "screen_tl"))

    def test_duplicate_component_ids_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate component_id"):
            UIIRPage(
                ir_version="0.1.0",
                page_id="p",
                matrix=MatrixSpec(width=10, height=10),
                aspect_mode="stretch",
                components=(
                    UIIRComponent(
                        component_id="dup",
                        component_type="text",
                        position=CoordinateRef(x=0, y=0),
                        width=1,
                        height=1,
                    ),
                    UIIRComponent(
                        component_id="dup",
                        component_type="svg",
                        position=CoordinateRef(x=1, y=1),
                        width=1,
                        height=1,
                    ),
                ),
            )

    def test_validate_payload_requires_core_fields(self) -> None:
        with self.assertRaises(TypeError):
            validate_ui_ir_payload({"page_id": "missing_stuff"})

    def test_schema_has_required_fields(self) -> None:
        schema = default_ui_ir_page_schema()
        self.assertIn("required", schema)
        self.assertIn("components", schema["required"])
        self.assertIn("matrix", schema["required"])


if __name__ == "__main__":
    unittest.main()
