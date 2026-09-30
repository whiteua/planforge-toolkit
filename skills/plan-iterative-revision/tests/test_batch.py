from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"

ROADMAP = """# Roadmap: plan

## Dependency graph

| Stage | Title | Depends on | Parallel group | Weight |
|---|---|---|---|---|
| a | First | — | A | 🟢 light |
| B | Second | a | B | 🟡 medium |

## Stages
"""


def run(*args: str, stdin: str = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True,
                          encoding="utf-8", input=stdin)


class Parts(unittest.TestCase):
    def test_lists_parts_in_table_order(self):
        with tempfile.TemporaryDirectory() as d:
            roadmap = Path(d) / "plan-roadmap.md"
            roadmap.write_text(ROADMAP, encoding="utf-8")
            (Path(d) / "plan-a.md").write_text("# a\n", encoding="utf-8")
            p = run("parts", str(roadmap))
            out = json.loads(p.stdout)
            self.assertEqual(p.returncode, 1, p.stdout)  # part b is missing
            self.assertEqual(out["base"], "plan")
            self.assertEqual([x["id"] for x in out["parts"]], ["a", "b"])
            self.assertEqual([x["exists"] for x in out["parts"]], [True, False])
            self.assertTrue(out["parts"][1]["path"].endswith("plan-b.md"))
            (Path(d) / "plan-b.md").write_text("# b\n", encoding="utf-8")
            self.assertEqual(run("parts", str(roadmap)).returncode, 0)

    def test_rejects_non_roadmap_and_old_ids(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "plan.md"
            plain.write_text("x", encoding="utf-8")
            self.assertEqual(run("parts", str(plain)).returncode, 2)
            roadmap = Path(d) / "plan-roadmap.md"
            roadmap.write_text(ROADMAP.replace("| a |", "| stg01 |"), encoding="utf-8")
            p = run("parts", str(roadmap))
            self.assertEqual(p.returncode, 2)
            self.assertIn("invalid part ids", json.loads(p.stdout)["error"])


class BatchSummary(unittest.TestCase):
    def test_worst_result_wins(self):
        results = {"parts": {
            "a": {"result": "clean", "iterations": 0, "remaining_issues": 0},
            "b": {"result": "converged", "iterations": 2, "remaining_issues": 1},
            "c": {"result": "limit", "iterations": 5, "remaining_issues": 3},
        }}
        p = run("batch-summary", "--results", "-", stdin=json.dumps(results))
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(out["result"], "limit")
        self.assertEqual(out["remaining_issues"], 4)
        self.assertEqual(out["counts"]["clean"], 1)
        self.assertEqual(set(out["parts"]), {"a", "b", "c"})

    def test_invalid_input(self):
        p = run("batch-summary", "--results", "-", stdin=json.dumps({"parts": {"a": {"result": "meh"}}}))
        self.assertEqual(p.returncode, 2)
        p = run("batch-summary", "--results", "-", stdin="not json")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
