from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"
VALID = ROOT / ".fixtures" / "_validator" / "valid-review.md"


def validate(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), "validate-review", str(path)],
        text=True, capture_output=True,
    )


class ValidatorTolerance(unittest.TestCase):
    def test_baseline_fixture_is_valid(self):
        p = validate(VALID)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_extra_audit_rows_and_escalated_status_are_tolerated(self):
        text = VALID.read_text(encoding="utf-8")
        # inject two optional Audit state rows right after the Audit state table header row
        marker = "## Audit state\n"
        self.assertIn(marker, text)
        injected_rows = (
            "| Lenses used | 2 | multi-lens audit |\n"
            "| Cache hits | 11 | memoized cross-checks |\n"
        )
        # append rows at end of the Audit state table: insert before the next blank line + "## Summary"
        text = text.replace("## Summary", injected_rows + "\n## Summary", 1)
        # add an ESCALATED status header near the top header block
        text = text.replace(
            "**Issues found**",
            "**Status**: ESCALATED — stuck issue needs manual decision\n**Issues found**",
            1,
        )
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "injected-review.md"
            target.write_text(text, encoding="utf-8", newline="\n")
            p = validate(target)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(json.loads(p.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
