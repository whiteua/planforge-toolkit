from __future__ import annotations

import json
import unittest
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets"


class ResultSchema(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ASSETS / "result.schema.json").read_text(encoding="utf-8"))
        self.example = json.loads((ASSETS / "result.example.json").read_text(encoding="utf-8"))

    def test_schema_declares_required_and_enum(self):
        self.assertEqual(self.schema["required"], ["result", "iterations", "remaining_issues"])
        self.assertEqual(
            self.schema["properties"]["result"]["enum"],
            ["clean", "converged", "stagnation", "limit", "escalated"],
        )

    def test_new_fields_declared(self):
        props = self.schema["properties"]
        self.assertEqual(props["lenses_used"]["maximum"], 4)
        self.assertIn("stop_reason", props)
        self.assertEqual(
            props["stop_reason"]["enum"],
            ["regression", "churn", "drain", "stuck", None],
        )
        self.assertIn("flows", props)
        self.assertIs(props["flows"]["additionalProperties"], False)
        self.assertEqual(
            set(props["flows"]["properties"]),
            {"new", "resolved", "persisted", "reintroduced"},
        )

    def test_result_enum_unchanged(self):
        self.assertEqual(
            self.schema["properties"]["result"]["enum"],
            ["clean", "converged", "stagnation", "limit", "escalated"],
        )

    def test_example_has_all_required_keys(self):
        for key in self.schema["required"]:
            self.assertIn(key, self.example)

    def test_example_result_in_enum(self):
        self.assertIn(self.example["result"], self.schema["properties"]["result"]["enum"])

    def test_example_stop_reason_in_enum_when_declared(self):
        if "stop_reason" in self.example:
            self.assertIn(
                self.example["stop_reason"],
                self.schema["properties"]["stop_reason"]["enum"],
            )

    def test_example_flows_shape_when_declared(self):
        if "flows" not in self.example:
            return

        flows = self.example["flows"]
        self.assertEqual(set(flows), {"new", "resolved", "persisted", "reintroduced"})
        for key, value in flows.items():
            with self.subTest(flow=key):
                self.assertIs(type(value), int)
                self.assertGreaterEqual(value, 0)

    def test_example_keys_are_declared(self):
        declared = set(self.schema["properties"])
        self.assertTrue(set(self.example).issubset(declared))


if __name__ == "__main__":
    unittest.main()
