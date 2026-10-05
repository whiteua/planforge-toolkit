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


class BootstrapNonUtf8Spec(unittest.TestCase):
    def test_a_spec_that_is_not_utf8_is_a_json_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a-spec.md").write_bytes("> Tier: Quick\n\n# Goal\n\nПривет\n".encode("cp1251"))
            plan = Path(d) / "a-impl.md"
            plan.write_text("**Spec:** a-spec.md\n\n### Task 1: x\n", encoding="utf-8")
            p = run("bootstrap", str(plan))
            self.assertEqual(p.returncode, 2, p.stderr)
            out = json.loads(p.stdout)
            self.assertIs(out["valid"], False)
            self.assertIn("cannot read", out["error"])


SPEC_TEXT = (
    "> Tier: Deep\n"
    "> Chain: revision=quick; stop=strict\n"
    "> Environment: `db_test` (test) — read=run, write=task — \"Читать db_test на весь прогон? — Да\" (2026-10-01)\n"
    "\n# Goal\n\nЦель.\n"
)


def write_spec_and_plan(d: Path, header: str = "") -> Path:
    (d / "s-spec.md").write_text(SPEC_TEXT, encoding="utf-8")
    plan = d / "plan.md"
    plan.write_text(f"# План\n\n**Spec:** s-spec.md\n\n**Tier:** Deep\n{header}\n### Task 1: шаг\n", encoding="utf-8")
    return plan


class BootstrapIncompletePlan(unittest.TestCase):
    def test_a_plan_with_the_writing_marker_is_not_valid(self):  # spec 3 of plan-refactoring-02
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / "a-impl.md"
            plan.write_text("# P\n\n### Task 1: A\n\n> Writing: in progress (spec sha256 0123456789ab)\n",
                            encoding="utf-8")
            p = run("bootstrap", str(plan))
            out = json.loads(p.stdout)
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertFalse(out["valid"])
            self.assertTrue(any(e.startswith("plan-incomplete: ") for e in out["errors"]), out["errors"])
            plan.write_text("# P\n\n### Task 1: A\n", encoding="utf-8")
            self.assertEqual(run("bootstrap", str(plan)).returncode, 0)


class BootstrapSettings(unittest.TestCase):
    def test_settings_from_spec(self):
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(run("bootstrap", str(write_spec_and_plan(Path(d)))).stdout)
            s = out["settings"]
            self.assertEqual(s["from"], "spec")
            self.assertTrue(s["source"].endswith("s-spec.md"))
            self.assertEqual((s["chain"]["revision"], s["chain"]["stop"]), ("quick", "strict"))
            self.assertEqual(s["environments"][0]["read"], "run")

    def test_part_follows_source_to_plan_and_spec(self):
        with tempfile.TemporaryDirectory() as d:
            write_spec_and_plan(Path(d))
            part = Path(d) / "plan-a.md"
            part.write_text("# Stage a: Часть\n\n> Source: [plan.md](./plan.md)\n\n## Tasks\n1. шаг\n", encoding="utf-8")
            out = json.loads(run("bootstrap", str(part)).stdout)
            self.assertEqual(out["settings"]["from"], "spec")
            self.assertEqual(out["settings"]["chain"]["revision"], "quick")

    def test_missing_spec_is_a_warning_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / "plan.md"
            plan.write_text("# Plan\n\n**Spec:** gone-spec.md\n\n### Task 1: x\n", encoding="utf-8")
            p = run("bootstrap", str(plan))
            out = json.loads(p.stdout)
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertIs(out["settings"]["ok"], False)
            self.assertTrue(any(w.startswith("settings: settings-source-missing") for w in out["warnings"]), out["warnings"])

    def test_without_brainstorm_tool_settings_is_null(self):
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "skills" / "plan-iterative-revision" / "scripts" / "next_review_index.py"
            copy.parent.mkdir(parents=True)
            shutil.copyfile(str(TOOL), str(copy))
            plan = Path(d) / "plan.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            p = subprocess.run([sys.executable, str(copy), "bootstrap", str(plan)], text=True, capture_output=True, encoding="utf-8")
            out = json.loads(p.stdout)
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertIsNone(out["settings"])
            self.assertIn("plan-brainstorming not installed alongside", " ".join(out["warnings"]))

    def test_explicit_chain_sets_preset_and_stop_policy(self):
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(run("bootstrap", str(write_spec_and_plan(Path(d)))).stdout)
            config = out["config"]
            self.assertEqual((config["preset"], config["max"], config["stop_policy"]), ("quick", 3, "strict"))
            self.assertEqual(out["config_from_settings"], ["preset", "stop_policy"])

    def test_plan_header_chain_wins_over_spec(self):
        with tempfile.TemporaryDirectory() as d:
            header = "\n**Chain:** split=never; revision=deep; stop=pragmatic; resolver=skip\n"
            out = json.loads(run("bootstrap", str(write_spec_and_plan(Path(d), header))).stdout)
            self.assertEqual(out["settings"]["from"], "plan-header")
            self.assertEqual((out["config"]["preset"], out["config"]["stop_policy"]), ("deep", "pragmatic"))

    def test_user_flags_win_over_settings(self):
        with tempfile.TemporaryDirectory() as d:
            out = json.loads(run("bootstrap", str(write_spec_and_plan(Path(d))), "--preset", "deep").stdout)
            self.assertEqual((out["config"]["preset"], out["config"]["stop_policy"]), ("deep", "strict"))
            self.assertEqual(out["config_from_settings"], ["stop_policy"])

    def test_no_chain_line_keeps_defaults_and_the_question(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s-spec.md").write_text("> Tier: Deep\n\n# Goal\n\nЦель.\n", encoding="utf-8")
            plan = Path(d) / "plan.md"
            plan.write_text("# План\n\n**Spec:** s-spec.md\n\n### Task 1: шаг\n", encoding="utf-8")
            out = json.loads(run("bootstrap", str(plan)).stdout)
            self.assertIs(out["settings"]["chain_explicit"], False)
            self.assertEqual(out["config"]["preset"], "standard")
            self.assertEqual(out["config_from_settings"], [])


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

    def test_backlog_at_the_root_is_a_free_file(self):
        run("guard-begin", str(self.root), "backlog")
        (self.root / "plan.md").write_text("plan v2\n", encoding="utf-8")
        (self.root / "BACKLOG.md").write_text("# Backlog\n\n- [ ] note\n", encoding="utf-8")
        p = run("guard-check", str(self.root), "backlog", str(self.root / "plan.md"))
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertEqual((out["changed"], out["violations"]), (["BACKLOG.md", "plan.md"], []))

    def test_backlog_elsewhere_and_other_files_stay_violations(self):
        run("guard-begin", str(self.root), "backlog-nested")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "BACKLOG.md").write_text("x\n", encoding="utf-8")
        (self.root / "BACKLOG.md").write_text("x\n", encoding="utf-8")
        (self.root / "code.py").write_text("x = 4\n", encoding="utf-8")
        p = run("guard-check", str(self.root), "backlog-nested", str(self.root / "plan.md"))
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertEqual(json.loads(p.stdout)["violations"], ["code.py", "docs/BACKLOG.md"])

    def test_check_without_begin(self):
        p = run("guard-check", str(self.root), "never-started", "plan.md")
        self.assertEqual(p.returncode, 2)


class BootstrapJournal(unittest.TestCase):
    """bootstrap returns the chain journal (brainstorm_tool.journal_path_for) when the file exists."""

    def test_journal_null_until_the_file_exists(self):
        with tempfile.TemporaryDirectory() as d:
            plan = write_spec_and_plan(Path(d))
            self.assertIsNone(json.loads(run("bootstrap", str(plan)).stdout)["journal"])
            journal = Path(d) / "s-chain.json"  # goal = spec name without -spec.md (no Backlog line)
            journal.write_text("{}\n", encoding="utf-8")
            p = run("bootstrap", str(plan))
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertEqual(Path(json.loads(p.stdout)["journal"]).resolve(), journal.resolve())

    def test_part_resolves_the_master_journal(self):
        with tempfile.TemporaryDirectory() as d:
            write_spec_and_plan(Path(d))
            (Path(d) / "s-chain.json").write_text("{}\n", encoding="utf-8")
            part = Path(d) / "plan-a.md"
            part.write_text("# Stage a: Часть\n\n> Source: [plan.md](./plan.md)\n\n## Tasks\n1. шаг\n", encoding="utf-8")
            out = json.loads(run("bootstrap", str(part)).stdout)
            self.assertEqual(Path(out["journal"]).resolve(), (Path(d) / "s-chain.json").resolve())

    def test_missing_spec_gives_null(self):
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / "plan.md"
            plan.write_text("# Plan\n\n**Spec:** gone-spec.md\n\n### Task 1: x\n", encoding="utf-8")
            p = run("bootstrap", str(plan))
            self.assertEqual(p.returncode, 0, p.stdout)
            self.assertIsNone(json.loads(p.stdout)["journal"])

    def test_old_or_failing_brainstorm_tool_gives_null(self):
        stubs = {
            "old": "def resolve_settings(path):\n    return {'errors': [], 'warnings': []}\n",
            "failing": (
                "def resolve_settings(path):\n    return {'errors': [], 'warnings': []}\n\n"
                "def journal_path_for(path):\n    raise RuntimeError('boom')\n"
            ),
        }
        for name, stub in stubs.items():
            with tempfile.TemporaryDirectory() as d:
                copy = Path(d) / "skills" / "plan-iterative-revision" / "scripts" / "next_review_index.py"
                copy.parent.mkdir(parents=True)
                shutil.copyfile(str(TOOL), str(copy))
                brainstorm = Path(d) / "skills" / "plan-brainstorming" / "scripts" / "brainstorm_tool.py"
                brainstorm.parent.mkdir(parents=True)
                brainstorm.write_text(stub, encoding="utf-8")
                plan = Path(d) / "plan.md"
                plan.write_text("# Plan\n", encoding="utf-8")
                p = subprocess.run([sys.executable, str(copy), "bootstrap", str(plan)], text=True, capture_output=True, encoding="utf-8")
                self.assertEqual(p.returncode, 0, name + p.stdout + p.stderr)
                self.assertIsNone(json.loads(p.stdout)["journal"], name)


if __name__ == "__main__":
    unittest.main()
