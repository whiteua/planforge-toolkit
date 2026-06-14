from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"


def review(n: int, fps: dict) -> str:
    lines = [f"# Ревизия {n}: demo", "", f"**Iteration**: {n}", "", "## Issues", ""]
    for index, (_label, (severity, category, fingerprint)) in enumerate(fps.items(), start=1):
        lines += [
            f"### [{n}.{index}] {severity} · {category} · {index}",
            "- **Required fix (contract)**:",
            f"  Fix {index} text",
            f"- **Fingerprint**: {fingerprint}",
            "",
        ]
    return "\n".join(lines)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True)


class Digest(unittest.TestCase):
    def test_empty_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = run("digest", d, "demo")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), {"iteration": 1, "active_contracts": [], "resolved_contracts": []})

    def test_active_and_resolved_split(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "demo-review-1.md").write_text(
                review(1, {"x": ("blocker", "logic", "aaaa1111"), "y": ("minor", "tests", "bbbb2222")}),
                encoding="utf-8",
            )
            Path(d, "demo-review-2.md").write_text(
                review(2, {"x": ("blocker", "logic", "aaaa1111")}),
                encoding="utf-8",
            )
            p = run("digest", d, "demo")
        out = json.loads(p.stdout)
        self.assertEqual(out["iteration"], 3)
        self.assertEqual([c["fingerprint"] for c in out["active_contracts"]], ["aaaa1111"])
        self.assertEqual(out["active_contracts"][0]["status"], "Open")
        self.assertEqual(out["active_contracts"][0]["severity"], "blocker")
        self.assertEqual(out["active_contracts"][0]["fix"], "Fix 1 text")
        self.assertEqual([c["fingerprint"] for c in out["resolved_contracts"]], ["bbbb2222"])
        self.assertEqual(out["resolved_contracts"][0]["status"], "Fixed")
        self.assertEqual(out["resolved_contracts"][0]["severity"], "minor")
        self.assertEqual(out["resolved_contracts"][0]["fix"], "Fix 2 text")