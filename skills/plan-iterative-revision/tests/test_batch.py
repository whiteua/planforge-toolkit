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

    def test_error_part_escalates_and_inline_json_is_clean_error(self):
        results = {"parts": {"a": {"result": "clean", "iterations": 0, "remaining_issues": 0},
                             "b": {"result": None, "error": "bootstrap: directory not writable"}}}
        p = run("batch-summary", "--results", "-", stdin=json.dumps(results))
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(out["result"], "escalated")
        self.assertEqual(out["counts"]["error"], 1)
        p = run("batch-summary", "--results", '{"parts": {}}')
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))

    def test_invalid_input(self):
        p = run("batch-summary", "--results", "-", stdin=json.dumps({"parts": {"a": {"result": "meh"}}}))
        self.assertEqual(p.returncode, 2)
        p = run("batch-summary", "--results", "-", stdin="not json")
        self.assertEqual(p.returncode, 2)


PART = "# Part a\n\n**Goal:** part.\n\n### Task 1: One\n\n- [ ] **Step 1: {one}**\n\n### Task 2: Two\n\n- [ ] **Step 1: two**\n"


class IncrementalPart(unittest.TestCase):
    def test_incremental_cycle_of_a_part_gives_the_same_batch_summary(self):
        issue = {"severity": "major", "category": "logic", "title": "T", "location_in_plan": "Task 1, Step 1",
                 "code_cross_check": "verified - checked", "problem": "P", "required_fix": "Fix A",
                 "acceptance": "A"}
        with tempfile.TemporaryDirectory() as d:
            part = Path(d) / "plan-a.md"
            part.write_text(PART.format(one="one"), encoding="utf-8")

            def record(issues, *flags):
                p = run("record", str(part), "--run-start", "1", "--max", "5", "--issues", "-", *flags,
                        stdin=json.dumps({"summary": "S.", "issues": issues}))
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                return json.loads(p.stdout)

            self.assertEqual(record([issue])["action"], "implement")
            part.write_text(PART.format(one="fixed"), encoding="utf-8")
            digest = json.loads(run("digest", d, "plan-a", "--since", "1").stdout)["task_digest"]
            self.assertEqual((digest["scope"], digest["tasks"]), ("incremental", ["1"]))
            self.assertEqual(record([], "--scope", "incremental", "--tasks", "1")["action"], "full-audit-required")
            final = record([], "--scope", "full")["final"]
            p = run("batch-summary", "--results", "-", stdin=json.dumps({"parts": {"a": final}}))
            out = json.loads(p.stdout)
            self.assertEqual((out["result"], out["remaining_issues"], out["counts"]["converged"]), ("converged", 0, 1))


if __name__ == "__main__":
    unittest.main()
