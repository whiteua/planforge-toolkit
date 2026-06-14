from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True)


class CompletionPath(unittest.TestCase):
    def test_returns_path_and_exists_false(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("completion-path", d, "my-plan")
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout)
            expected = str(Path(d) / "my-plan-completion.md")
            self.assertEqual(out["path"], expected)
            self.assertFalse(out["exists"])

    def test_returns_exists_true_when_file_present(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "my-plan-completion.md"
            target.write_text("done", encoding="utf-8")
            p = run("completion-path", d, "my-plan")
            self.assertEqual(p.returncode, 0, p.stderr)
            out = json.loads(p.stdout)
            self.assertTrue(out["exists"])

    def test_usage_error_with_wrong_argc(self):
        p = run("completion-path", "only-one-arg")
        self.assertEqual(p.returncode, 64)
        self.assertIn("usage", p.stderr)


if __name__ == "__main__":
    unittest.main()
