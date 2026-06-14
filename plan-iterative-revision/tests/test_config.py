from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True)


class ResolveConfig(unittest.TestCase):
    def test_default_is_standard(self):
        p = run("resolve-config")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(
            json.loads(p.stdout),
            {"preset": "standard", "lenses": 2, "rigor": "read", "max": 5, "stop_policy": "pragmatic"},
        )

    def test_quick_preset(self):
        d = json.loads(run("resolve-config", "--preset", "quick").stdout)
        self.assertEqual((d["lenses"], d["rigor"], d["max"]), (1, "grep", 3))

    def test_deep_preset(self):
        d = json.loads(run("resolve-config", "--preset", "deep").stdout)
        self.assertEqual((d["lenses"], d["rigor"], d["max"]), (3, "explore", 7))

    def test_override_wins_over_preset(self):
        d = json.loads(run("resolve-config", "--preset", "deep", "--lenses", "1", "--max", "2").stdout)
        self.assertEqual((d["lenses"], d["max"]), (1, 2))
        self.assertEqual(d["rigor"], "explore")

    def test_stop_policy_override(self):
        d = json.loads(run("resolve-config", "--stop-policy", "strict").stdout)
        self.assertEqual(d["stop_policy"], "strict")

    def test_bad_preset(self):
        p = run("resolve-config", "--preset", "ultra")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))

    def test_bad_lenses(self):
        p = run("resolve-config", "--lenses", "4")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))

    def test_bad_max(self):
        p = run("resolve-config", "--max", "0")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))

    def test_bad_rigor(self):
        p = run("resolve-config", "--rigor", "skim")
        self.assertEqual(p.returncode, 2)
        self.assertIn("error", json.loads(p.stdout))


if __name__ == "__main__":
    unittest.main()
