from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"


def review(n: int, fps: list) -> str:
    lines = [f"# Ревизия {n}: demo", "", f"**Iteration**: {n}", "", "## Issues", ""]
    for k, fp in enumerate(fps, start=1):
        lines += [
            f"### [{n}.{k}] major · logic · {k}",
            "- **Required fix (contract)**:",
            f"  Fix {k}",
            f"- **Fingerprint**: {fp}",
            "",
        ]
    return "\n".join(lines)


def run(*args, stdin: str = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True, input=stdin)


class FlowAnalyze(unittest.TestCase):
    def test_regression_from_history(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo-review-1.md").write_text(review(1, ["aaaa1111"]), encoding="utf-8")
            Path(d, "demo-review-2.md").write_text(review(2, []), encoding="utf-8")
            cur = Path(d) / "cur.json"
            cur.write_text(json.dumps(["aaaa1111"]), encoding="utf-8")
            p = run("flow-analyze", d, "demo", "--current", str(cur))
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(out["iteration"], 3)
        self.assertEqual(out["result"], "escalated")
        self.assertEqual(out["stop_reason"], "regression")
        self.assertEqual(out["flows"]["reintroduced"], 1)

    def test_stdin_object_form(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo-review-1.md").write_text(review(1, ["aaaa1111", "bbbb2222"]), encoding="utf-8")
            p = run(
                "flow-analyze",
                d,
                "demo",
                "--current",
                "-",
                stdin=json.dumps({"fingerprints": ["bbbb2222", "cccc3333"]}),
            )
        out = json.loads(p.stdout)
        self.assertEqual(out["flows"], {"new": 1, "resolved": 1, "persisted": 1, "reintroduced": 0})
        self.assertEqual(out["result"], "continue")
        self.assertIsNone(out["stop_reason"])

    def test_invalid_json_stdin_returns_json_error(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo-review-1.md").write_text(review(1, ["aaaa1111"]), encoding="utf-8")
            p = run("flow-analyze", d, "demo", "--current", "-", stdin="not json")
        out = json.loads(p.stdout)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("error", out)
        self.assertNotIn("Traceback", p.stderr)

    def test_invalid_fingerprints_shape_returns_json_error(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo-review-1.md").write_text(review(1, ["aaaa1111"]), encoding="utf-8")
            p = run(
                "flow-analyze",
                d,
                "demo",
                "--current",
                "-",
                stdin=json.dumps({"fingerprints": "aaaa1111"}),
            )
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", out)