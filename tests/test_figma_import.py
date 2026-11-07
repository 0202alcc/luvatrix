from __future__ import annotations

import unittest

from luvatrix_ui.figma_import import import_figma_document
from luvatrix_ui.planes_container import compile_container


def _solid(r: float, g: float, b: float, opacity: float = 1.0) -> dict[str, object]:
    return {"type": "SOLID", "color": {"r": r, "g": g, "b": b}, "opacity": opacity}


def _figma_document() -> dict[str, object]:
    return {
        "name": "Demo",
        "document": {
            "id": "0:0",
            "name": "Document",
            "type": "DOCUMENT",
            "children": [
                {
                    "id": "0:1",
                    "name": "Page 1",
                    "type": "CANVAS",
                    "prototypeStartNodeID": "10:1",
                    "children": [
                        {
                            "id": "10:1",
                            "name": "Home",
                            "type": "FRAME",
                            "absoluteBoundingBox": {"x": 0, "y": 0, "width": 390, "height": 844},
                            "fills": [_solid(0.04, 0.06, 0.13)],
                            "children": [
                                {
                                    "id": "10:2",
                                    "name": "Title",
                                    "type": "TEXT",
                                    "absoluteBoundingBox": {"x": 24, "y": 40, "width": 200, "height": 32},
                                    "characters": "Welcome",
                                    "style": {"fontFamily": "Inter", "fontSize": 24},
                                    "fills": [_solid(1.0, 1.0, 1.0)],
                                },
                                {
                                    "id": "10:3",
                                    "name": "GoButton",
                                    "type": "RECTANGLE",
                                    "absoluteBoundingBox": {"x": 24, "y": 720, "width": 120, "height": 44},
                                    "fills": [_solid(0.2, 0.4, 1.0)],
                                    "interactions": [
                                        {
                                            "trigger": {"type": "CLICK"},
                                            "actions": [
                                                {
                                                    "type": "NODE",
                                                    "destinationId": "10:10",
                                                    "transition": {
                                                        "type": "MOVE_IN_LEFT",
                                                        "duration": 0.3,
                                                        "easing": {"type": "EASE_OUT"},
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            "id": "10:10",
                            "name": "Settings",
                            "type": "FRAME",
                            "absoluteBoundingBox": {"x": 390, "y": 0, "width": 390, "height": 844},
                            "fills": [_solid(0.1, 0.1, 0.12)],
                            "children": [],
                        },
                    ],
                }
            ],
        },
    }


class FigmaImportRouteTests(unittest.TestCase):
    def test_import_creates_route_per_top_level_frame(self) -> None:
        result = import_figma_document(_figma_document())

        routes = result.container_payload["routes"]
        self.assertEqual([route["id"] for route in routes], ["home", "settings"])

    def test_import_uses_prototype_start_node_as_entry_route(self) -> None:
        result = import_figma_document(_figma_document())

        compiled = compile_container(result.container_payload)
        self.assertEqual(compiled.entry_route, "home")

    def test_import_maps_interaction_to_route_transition(self) -> None:
        result = import_figma_document(_figma_document())

        home_route = result.container_payload["routes"][0]
        transitions = home_route["transitions"]
        self.assertEqual(len(transitions), 1)
        transition = transitions[0]
        self.assertEqual(transition["trigger"], "navigate_settings")
        self.assertEqual(transition["to_route"], "settings")
        self.assertEqual(transition["kind"], "slide_left")
        self.assertEqual(transition["duration_ms"], 300)
        self.assertEqual(transition["easing"], "ease_out")

    def test_import_result_passes_container_compile(self) -> None:
        result = import_figma_document(_figma_document())

        compiled = compile_container(result.container_payload)
        self.assertEqual([route.id for route in compiled.routes], ["home", "settings"])


class FigmaImportComponentTests(unittest.TestCase):
    def test_import_maps_text_node_to_text_component(self) -> None:
        result = import_figma_document(_figma_document())

        components = result.container_payload["components"]
        text_components = [c for c in components if c["type"] == "text"]
        self.assertEqual(len(text_components), 1)
        text = text_components[0]
        self.assertEqual(text["id"], "text_10_2")
        self.assertEqual(text["attach_to"], "plane_home")
        self.assertEqual(text["props"]["text"], "Welcome")
        self.assertEqual(text["props"]["appearance"]["color_hex"], "#FFFFFF")

    def test_import_text_position_is_relative_to_parent_frame(self) -> None:
        result = import_figma_document(_figma_document())

        components = result.container_payload["components"]
        text = next(c for c in components if c["type"] == "text")
        self.assertEqual(text["position"], {"x": 24, "y": 40, "frame": "screen_tl"})

    def test_import_maps_shape_to_svg_asset_component(self) -> None:
        result = import_figma_document(_figma_document())

        components = result.container_payload["components"]
        shape = next(c for c in components if c["type"] == "svg")
        self.assertEqual(shape["id"], "svg_10_3")
        self.assertEqual(shape["attach_to"], "plane_home")
        self.assertEqual(shape["props"]["svg"], "assets/svg_10_3.svg")
        self.assertIn("assets/svg_10_3.svg", result.assets)
        markup = result.assets["assets/svg_10_3.svg"]
        self.assertIn("<svg", markup)
        self.assertIn('fill="#3366FF"', markup)

    def test_import_frame_background_becomes_plane_background(self) -> None:
        result = import_figma_document(_figma_document())

        planes = result.container_payload["planes"]
        home_plane = next(p for p in planes if p["id"] == "plane_home")
        self.assertEqual(home_plane["background"], {"color": "#0A0F21"})

    def test_import_sizes_use_pixel_units(self) -> None:
        result = import_figma_document(_figma_document())

        components = result.container_payload["components"]
        text = next(c for c in components if c["type"] == "text")
        self.assertEqual(text["size"]["width"], {"unit": "px", "value": 200})
        self.assertEqual(text["size"]["height"], {"unit": "px", "value": 32})


def _gradient_fill() -> dict[str, object]:
    return {
        "type": "GRADIENT_LINEAR",
        "gradientHandlePositions": [
            {"x": 0.0, "y": 0.0},
            {"x": 1.0, "y": 0.0},
            {"x": 0.0, "y": 1.0},
        ],
        "gradientStops": [
            {"position": 0.0, "color": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0}},
            {"position": 1.0, "color": {"r": 0.0, "g": 0.0, "b": 1.0, "a": 1.0}},
        ],
    }


class FigmaImportGradientTests(unittest.TestCase):
    def test_linear_gradient_becomes_svg_gradient_def(self) -> None:
        document = _figma_document()
        home_frame = document["document"]["children"][0]["children"][0]
        home_frame["children"][1]["fills"] = [_gradient_fill()]

        result = import_figma_document(document)

        markup = result.assets["assets/svg_10_3.svg"]
        self.assertIn("<linearGradient", markup)
        self.assertIn('offset="0.000"', markup)
        self.assertIn('offset="1.000"', markup)
        self.assertIn('stop-color="#FF0000"', markup)
        self.assertIn('stop-color="#0000FF"', markup)
        self.assertIn("url(#grad_10_3)", markup)

    def test_radial_gradient_maps_to_radial_gradient_def(self) -> None:
        document = _figma_document()
        home_frame = document["document"]["children"][0]["children"][0]
        radial = dict(_gradient_fill())
        radial["type"] = "GRADIENT_RADIAL"
        home_frame["children"][1]["fills"] = [radial]

        result = import_figma_document(document)

        markup = result.assets["assets/svg_10_3.svg"]
        self.assertIn("<radialGradient", markup)
        self.assertIn("url(#grad_10_3)", markup)


class FigmaImportAutoLayoutTests(unittest.TestCase):
    def test_auto_layout_children_without_bounds_get_computed_positions(self) -> None:
        document = _figma_document()
        home_frame = document["document"]["children"][0]["children"][0]
        home_frame["layoutMode"] = "VERTICAL"
        home_frame["itemSpacing"] = 10
        home_frame["paddingTop"] = 10
        home_frame["paddingLeft"] = 10
        stack_child = {
            "id": "20:1",
            "name": "Row",
            "type": "RECTANGLE",
            "width": 180,
            "height": 40,
            "fills": [_solid(0.5, 0.5, 0.5)],
        }
        stack_child2 = {
            "id": "20:2",
            "name": "Row2",
            "type": "RECTANGLE",
            "width": 180,
            "height": 40,
            "fills": [_solid(0.6, 0.6, 0.6)],
        }
        home_frame["children"] = [stack_child, stack_child2]

        result = import_figma_document(document)

        components = result.container_payload["components"]
        by_id = {c["id"]: c for c in components}
        first = by_id["svg_20_1"]
        second = by_id["svg_20_2"]
        self.assertEqual(first["position"], {"x": 10, "y": 10, "frame": "screen_tl"})
        # Stacked below the first child plus itemSpacing.
        self.assertEqual(second["position"], {"x": 10, "y": 60, "frame": "screen_tl"})

    def test_horizontal_auto_layout_stacks_along_x(self) -> None:
        document = _figma_document()
        home_frame = document["document"]["children"][0]["children"][0]
        home_frame["layoutMode"] = "HORIZONTAL"
        home_frame["itemSpacing"] = 8
        home_frame["paddingLeft"] = 4
        home_frame["paddingTop"] = 0
        first = {"id": "21:1", "name": "A", "type": "RECTANGLE", "width": 100, "height": 40, "fills": [_solid(0.1, 0.1, 0.1)]}
        second = {"id": "21:2", "name": "B", "type": "RECTANGLE", "width": 100, "height": 40, "fills": [_solid(0.2, 0.2, 0.2)]}
        home_frame["children"] = [first, second]

        result = import_figma_document(document)

        by_id = {c["id"]: c for c in result.container_payload["components"]}
        self.assertEqual(by_id["svg_21_1"]["position"]["x"], 4)
        self.assertEqual(by_id["svg_21_2"]["position"]["x"], 112)


class FigmaImportComponentInstanceTests(unittest.TestCase):
    def test_top_level_component_nodes_do_not_become_routes(self) -> None:
        document = _figma_document()
        page = document["document"]["children"][0]
        page["children"].append(
            {
                "id": "30:1",
                "name": "ButtonTemplate",
                "type": "COMPONENT",
                "absoluteBoundingBox": {"x": 800, "y": 0, "width": 100, "height": 40},
                "fills": [_solid(0.2, 0.4, 1.0)],
                "children": [],
            }
        )

        result = import_figma_document(document)

        routes = result.container_payload["routes"]
        self.assertEqual([route["id"] for route in routes], ["home", "settings"])
        planes = result.container_payload["planes"]
        self.assertEqual([p["id"] for p in planes], ["plane_home", "plane_settings"])

    def test_instance_node_imports_children_like_frame(self) -> None:
        document = _figma_document()
        home_frame = document["document"]["children"][0]["children"][0]
        home_frame["children"].append(
            {
                "id": "31:1",
                "name": "Badge",
                "type": "INSTANCE",
                "absoluteBoundingBox": {"x": 200, "y": 100, "width": 60, "height": 24},
                "fills": [_solid(0.9, 0.9, 0.9)],
                "children": [
                    {
                        "id": "31:2",
                        "name": "BadgeLabel",
                        "type": "TEXT",
                        "absoluteBoundingBox": {"x": 205, "y": 105, "width": 50, "height": 14},
                        "characters": "New",
                        "style": {"fontFamily": "Inter", "fontSize": 12},
                        "fills": [_solid(0, 0, 0)],
                    }
                ],
            }
        )

        result = import_figma_document(document)

        components = result.container_payload["components"]
        text_ids = [c["id"] for c in components if c["type"] == "text"]
        self.assertIn("text_31_2", text_ids)
        badge_text = next(c for c in components if c["id"] == "text_31_2")
        self.assertEqual(badge_text["position"], {"x": 5, "y": 5, "frame": "screen_tl"})


if __name__ == "__main__":
    unittest.main()
