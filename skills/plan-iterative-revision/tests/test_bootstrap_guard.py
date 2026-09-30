from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "next_review_index.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True, encoding="utf-8")


class Bootstrap(unittest.TestCase):
    def test_fields_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / "my-plan.md"
            plan.write_text("# Plan\n\nEnglish text only.\n", encoding="utf-8")
            (Path(d) / "my-plan-review-2.md").write_text("x", encoding="utf-8")
            p = run("bootstrap", str(plan))
            out = json.loads(p.stdout)
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertTrue(out["valid"])
            self.assertEqual(out["basename"], "my-plan")
            self.assertEqual(out["lang"], "en")
            self.assertEqual(out["run_start"], 3)
            self.assertTrue(out["prev_review"].endswith("my-plan-review-2.md"))
            self.assertTrue(out["next_review"].endswith("my-plan-review-3.md"))
            self.assertEqual(out["config"]["preset"], "standard")
            self.assertEqual(list(Path(d).glob(".*.tmp")), [])

    def test_russian_and_config_flags(self):
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / "plan.md"
            plan.write_text("# План\n\nРусский текст плана.\n", encoding="utf-8")
            out = json.loads(run("bootstrap", str(plan), "--preset", "deep").stdout)
            self.assertEqual(out["lang"], "ru")
            self.assertEqual((out["config"]["lenses"], out["config"]["max"]), (4, 7))

    def test_errors(self):
        p = run("bootstrap", "no/such/plan.md")
        self.assertEqual(p.returncode, 2)
        self.assertIs(json.loads(p.stdout)["valid"], False)
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / "plan.md"
            plan.write_text("x", encoding="utf-8")
            self.assertEqual(run("bootstrap", str(plan), "--preset", "ultra").returncode, 2)


@unittest.skipIf(shutil.which("git") is None, "git not available")
class Guard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.root), *cmd], check=True)
        (self.root / "plan.md").write_text("plan\n", encoding="utf-8")
        (self.root / "code.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "init"], check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_allowed_change_passes_and_snapshot_is_outside_repo(self):
        self.assertEqual(run("guard-begin", str(self.root), "phase-b").returncode, 0)
        (self.root / "plan.md").write_text("plan v2\n", encoding="utf-8")
        p = run("guard-check", str(self.root), "phase-b", str(self.root / "plan.md"))
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual(out["changed"], ["plan.md"])
        status = subprocess.run(["git", "-C", str(self.root), "status", "--porcelain"], capture_output=True, text=True)
        self.assertEqual(status.stdout.strip(), "M plan.md")

    def test_violation_on_other_file_even_if_already_dirty(self):
        (self.root / "code.py").write_text("x = 2\n", encoding="utf-8")
        run("guard-begin", str(self.root), "phase-a")
        (self.root / "code.py").write_text("x = 3\n", encoding="utf-8")
        p = run("guard-check", str(self.root), "phase-a", "plan-review-1.md")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)["violations"], ["code.py"])

    def test_non_ascii_path_changes_are_seen(self):
        plan = self.root / "план.md"
        plan.write_text("v1\n", encoding="utf-8")
        run("guard-begin", str(self.root), "unicode")
        plan.write_text("v2\n", encoding="utf-8")
        (self.root / "code.py").write_text("x = 9\n", encoding="utf-8")
        p = run("guard-check", str(self.root), "unicode", str(plan))
        out = json.loads(p.stdout)
        self.assertEqual(out["changed"], ["code.py", "план.md"])
        self.assertEqual(out["violations"], ["code.py"])
        self.assertEqual(p.returncode, 1)

    def test_check_without_begin(self):
        p = run("guard-check", str(self.root), "never-started", "plan.md")
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
