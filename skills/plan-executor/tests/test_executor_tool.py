import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "executor_tool.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("executor_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDispatcher(unittest.TestCase):
    def test_unknown_command_fails(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH), "no-such-cmd"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

    def test_help_lists_registered_commands(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("detect-input", result.stdout)
        self.assertIn("parse-roadmap", result.stdout)
        self.assertIn("parse-tasks", result.stdout)


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_valid_ledger_has_no_errors(self):
        obj = {
            "version": 1,
            "plan_path": "/tmp/p.md",
            "input_type": "staged",
            "created_at": "2026-01-01T00:00:00Z",
            "units": [
                {
                    "id": "stg01",
                    "title": "T",
                    "weight": "green",
                    "status": "pending",
                    "attempts": 0,
                    "depends": [],
                    "parallel_group": "A",
                    "last_error": None,
                    "checkpoint_id": None,
                }
            ],
        }

        self.assertEqual(self.tool.validate_ledger(obj), [])

    def test_missing_units_returns_error(self):
        obj = {
            "version": 1,
            "plan_path": "/tmp/p.md",
            "input_type": "staged",
            "created_at": "...",
        }

        self.assertEqual(self.tool.validate_ledger(obj), ["missing field: units"])

    def test_bad_weight_returns_error(self):
        obj = {
            "version": 1,
            "plan_path": "/tmp/p.md",
            "input_type": "staged",
            "created_at": "2026-01-01T00:00:00Z",
            "units": [
                {
                    "id": "stg01",
                    "title": "T",
                    "weight": "purple",
                    "status": "pending",
                    "attempts": 0,
                    "depends": [],
                    "parallel_group": "A",
                    "last_error": None,
                    "checkpoint_id": None,
                }
            ],
        }

        self.assertEqual(self.tool.validate_ledger(obj), ["invalid weight: purple"])


class TestDetectInput(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_detects_staged_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "Plan002-plan.md"
            roadmap = root / "Plan002-plan-roadmap.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            roadmap.write_text("# Roadmap\n", encoding="utf-8")

            result = self.tool.detect_input(str(plan))

        self.assertEqual(result["input_type"], "staged")
        self.assertEqual(Path(result["roadmap"]).name, roadmap.name)

    def test_detects_whole_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("# Plan\n", encoding="utf-8")

            result = self.tool.detect_input(str(plan))

        self.assertEqual(result, {"input_type": "whole", "roadmap": None})

    def test_ignores_foreign_roadmap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan02.md"
            foreign = root / "plan01-roadmap.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            foreign.write_text("# Roadmap\n", encoding="utf-8")

            result = self.tool.detect_input(str(plan))

        self.assertEqual(result, {"input_type": "whole", "roadmap": None})

    def test_roadmap_path_as_input_is_staged_self(self):
        with tempfile.TemporaryDirectory() as tmp:
            roadmap = Path(tmp) / "plan01-roadmap.md"
            roadmap.write_text("# Roadmap\n", encoding="utf-8")

            result = self.tool.detect_input(str(roadmap))

        self.assertEqual(result["input_type"], "staged")
        self.assertEqual(Path(result["roadmap"]).name, roadmap.name)

    def test_force_whole_overrides_existing_roadmap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan01.md"
            roadmap = root / "plan01-roadmap.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            roadmap.write_text("# Roadmap\n", encoding="utf-8")

            result = self.tool.detect_input(str(plan), force_whole=True)

        self.assertEqual(result, {"input_type": "whole", "roadmap": None})


class TestParseRoadmap(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_parses_ru_table_and_normalizes_weight(self):
        text = """
| Стадия | Название | Зависит от | Параллельная группа | Вес |
|--------|----------|------------|---------------------|-----|
| stg01 | Scaffold | — | A | 🟡 medium |
| stg02 | Ledger | stg01 | B | 🔴 heavy |
"""

        rows = self.tool.parse_roadmap_table(text)

        self.assertEqual(rows[0], {"stage": "stg01", "title": "Scaffold", "depends": [], "group": "A", "weight": "yellow"})
        self.assertEqual(rows[1]["depends"], ["stg01"])
        self.assertEqual(rows[1]["weight"], "red")

    def test_parses_en_table(self):
        text = """
| Stage | Title | Depends on | Parallel group | Weight |
|-------|-------|------------|----------------|--------|
| stg01 | Scaffold | - | A | green |
| stg02 | Ledger | stg01, stg03 | B | yellow |
"""

        rows = self.tool.parse_roadmap_table(text)

        self.assertEqual(rows[1]["depends"], ["stg01", "stg03"])
        self.assertEqual(rows[0]["weight"], "green")


class TestRoadmapCycle(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_detect_cycle_raises(self):
        graph = {"stg01": ["stg02"], "stg02": ["stg01"]}

        with self.assertRaises(ValueError) as caught:
            self.tool.detect_cycle(graph)

        self.assertIn("stg01", str(caught.exception))


class TestParseTasks(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_extracts_structured_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("## Task 1: First\nBody\n### Task abc: Second\n", encoding="utf-8")

            result = self.tool.parse_tasks(str(plan))

        self.assertEqual([(u["id"], u["title"], u["weight"]) for u in result["units"]],
                         [("task-1", "First", "yellow"), ("task-abc", "Second", "yellow")])
        self.assertEqual([u["depends"] for u in result["units"]], [[], ["task-1"]])

    def test_empty_text_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("plain prose", encoding="utf-8")

            result = self.tool.parse_tasks(str(plan))

        self.assertEqual(result, {"units": []})

    def test_parse_tasks_russian_headings(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("### Задача 1: Первая\n\n### Задача 2.1: Вторая\n", encoding="utf-8")

            result = self.tool.parse_tasks(str(plan))

        self.assertEqual([u["id"] for u in result["units"]], ["task-1", "task-2.1"])


class TestParseTasksExtended(unittest.TestCase):
    """Tests for extended _TASK_RE keywords and separators (Task 1)."""

    def setUp(self):
        self.tool = load_tool()

    def _write_plan(self, content):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        tmp.write(content)
        tmp.close()
        return tmp.name

    def test_step_keyword_colon(self):
        path = self._write_plan("## Step 1: Alpha\n\n## Step 2: Beta\n")
        result = self.tool.parse_tasks(path)
        # IDs are always prefixed with 'task-'; keyword is stripped
        self.assertEqual([u["id"] for u in result["units"]], ["task-1", "task-2"])

    def test_phase_keyword_dash(self):
        path = self._write_plan("## Phase 1 - Setup\n\n## Phase 2 - Teardown\n")
        result = self.tool.parse_tasks(path)
        self.assertEqual([u["id"] for u in result["units"]], ["task-1", "task-2"])

    def test_stage_keyword_emdash(self):
        path = self._write_plan("## Stage A — Init\n\n## Stage B — Deploy\n")
        result = self.tool.parse_tasks(path)
        self.assertEqual([u["id"] for u in result["units"]], ["task-A", "task-B"])

    def test_dot_separator_with_space(self):
        path = self._write_plan("## Task 1. First\n\n## Task 2. Second\n")
        result = self.tool.parse_tasks(path)
        self.assertEqual([u["id"] for u in result["units"]], ["task-1", "task-2"])

    def test_russian_shag_keyword(self):
        path = self._write_plan("## Шаг 1: Первый\n\n## Шаг 2: Второй\n")
        result = self.tool.parse_tasks(path)
        self.assertEqual([u["id"] for u in result["units"]], ["task-1", "task-2"])

    def test_case_insensitive_keywords(self):
        path = self._write_plan("## TASK 1: Upper\n\n## task 2: lower\n")
        result = self.tool.parse_tasks(path)
        self.assertEqual(len(result["units"]), 2)

    def test_dot_id_not_split_by_separator(self):
        """Dotted IDs like 2.1 must survive with colon separator."""
        path = self._write_plan("### Task 2.1: Sub-task\n")
        result = self.tool.parse_tasks(path)
        self.assertEqual(result["units"][0]["id"], "task-2.1")


class TestExtractH1(unittest.TestCase):
    """Tests for _extract_h1 helper (Task 2)."""

    def setUp(self):
        self.tool = load_tool()

    def _write_plan(self, content, stem="myplan"):
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                          encoding="utf-8",
                                          prefix=stem + "_")
        tmp.write(content)
        tmp.close()
        return tmp.name

    def test_returns_h1_title(self):
        path = self._write_plan("# My Great Plan\n\nSome text\n")
        result = self.tool._extract_h1(path)
        self.assertEqual(result, "My Great Plan")

    def test_fallback_to_stem_when_no_h1(self):
        import os
        import tempfile as tf
        tmp = tf.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                    encoding="utf-8")
        tmp.write("## Task 1: Something\n")
        tmp.close()
        result = self.tool._extract_h1(tmp.name)
        # Should return the file stem (no H1 present)
        from pathlib import Path
        self.assertEqual(result, Path(tmp.name).stem)

    def test_ignores_h2_as_h1(self):
        """H2 headers (##) are NOT H1; _extract_h1 must look only for single-# lines."""
        path = self._write_plan("## Section Heading\n\nsome text\n")
        from pathlib import Path
        result = self.tool._extract_h1(path)
        # No H1 present; should fall back to file stem
        self.assertEqual(result, Path(path).stem)


class TestWholeFallback(unittest.TestCase):
    """Tests for single-unit fallback when --whole is set and no tasks found (Task 3)."""

    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _plan(self, content, name="plan.md"):
        p = Path(self.tmp.name) / name
        p.write_text(content, encoding="utf-8")
        return str(p)

    def _exec_dir(self):
        d = Path(self.tmp.name) / "exec"
        return str(d)

    def test_whole_fallback_uses_h1_as_title(self):
        """--whole + no task headings → single 'whole' unit with H1 title."""
        import types
        plan = self._plan("# My Big Plan\n\nJust prose, no tasks.\n")
        args = types.SimpleNamespace(plan_path=plan, exec_dir=self._exec_dir(), whole=True)

        result = self.tool.cmd_ledger_init(args)
        units = result["units"]
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["id"], "whole")
        self.assertEqual(units[0]["title"], "My Big Plan")

    def test_whole_fallback_uses_stem_when_no_h1(self):
        """--whole + no H1 → title falls back to file stem."""
        import types
        plan = self._plan("Just prose.\n", name="my-plan.md")
        args = types.SimpleNamespace(plan_path=plan, exec_dir=self._exec_dir(), whole=True)

        result = self.tool.cmd_ledger_init(args)
        self.assertEqual(result["units"][0]["title"], "my-plan")

    def test_structured_plan_not_affected_by_whole_flag(self):
        """Even with --whole, a plan WITH task headings still parses normally."""
        import types
        plan = self._plan("# Plan\n\n## Task 1: First\n\n## Task 2: Second\n")
        args = types.SimpleNamespace(plan_path=plan, exec_dir=self._exec_dir(), whole=True)

        result = self.tool.cmd_ledger_init(args)
        self.assertEqual(len(result["units"]), 2)
        self.assertEqual(result["units"][0]["id"], "task-1")


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exec_dir = Path(self.tmp.name) / "exec"
        self.plan_path = Path(self.tmp.name) / "Plan.md"
        self.plan_path.write_text("# Plan\n", encoding="utf-8")

    def units(self):
        return [
            {"stage": "stg01", "title": "Scaffold", "depends": [], "group": "A", "weight": "green"},
            {"stage": "stg02", "title": "Ledger", "depends": ["stg01"], "group": "B", "weight": "yellow"},
        ]


class TestLedgerInit(LedgerTestCase):
    def test_creates_valid_state(self):
        ledger = self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())

        self.assertTrue((self.exec_dir / "state.json").exists())
        self.assertEqual(self.tool.validate_ledger(ledger), [])
        self.assertEqual(ledger["units"][0]["id"], "stg01")
        self.assertEqual(ledger["units"][0]["parallel_group"], "A")
        self.assertTrue(all(unit["status"] == "pending" for unit in ledger["units"]))
        self.assertTrue(all(unit["attempts"] == 0 for unit in ledger["units"]))


class TestLedgerInitIdempotent(LedgerTestCase):
    def test_adopts_existing_and_recovers_running(self):
        ledger = self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        ledger["units"][0]["status"] = "running"
        ledger["units"][0]["attempts"] = 2
        ledger["units"][1]["status"] = "done"
        self.tool._save(str(self.exec_dir), ledger)

        recovered = self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", [])

        self.assertEqual(recovered["units"][0]["status"], "pending")
        self.assertEqual(recovered["units"][0]["attempts"], 2)
        self.assertEqual(recovered["units"][1]["status"], "done")

    def test_corrupt_state_raises(self):
        self.exec_dir.mkdir(parents=True)
        (self.exec_dir / "state.json").write_text("{", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())


class TestLedgerMark(LedgerTestCase):
    def setUp(self):
        super().setUp()
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())

    def test_running_failed_pending_done_transitions(self):
        running = self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.assertEqual(running["attempts"], 1)
        self.assertEqual(running["status"], "running")

        failed = self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="boom")
        self.assertEqual(failed["last_error"], "boom")
        self.assertFalse(failed["stagnation"])

        pending = self.tool.ledger_mark(str(self.exec_dir), "stg01", "pending")
        self.assertEqual(pending["attempts"], 1)
        self.assertIsNone(pending["last_error"])

        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        done = self.tool.ledger_mark(str(self.exec_dir), "stg01", "done", checkpoint="abc123")
        self.assertEqual(done["checkpoint_id"], "abc123")
        self.assertIsNone(done["last_error"])
        self.assertEqual(self.tool.ledger_mark(str(self.exec_dir), "stg01", "done", checkpoint="abc123"), done)

    def test_mark_running_on_running_raises(self):
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")

        with self.assertRaises(ValueError):
            self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")


class TestStagnation(LedgerTestCase):
    """Stagnation detection uses the direct failed -> running retry path."""

    def setUp(self):
        super().setUp()
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())

    def test_mark_failed_stores_previous_error(self):
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="first")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        result = self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="second")

        self.assertEqual(result["previous_error"], "first")
        self.assertEqual(result["last_error"], "second")

    def test_mark_failed_stagnation_true(self):
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="same")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        result = self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="same")

        self.assertTrue(result["stagnation"])

    def test_mark_failed_different_error_no_stagnation(self):
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="aaa")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        result = self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="bbb")

        self.assertFalse(result["stagnation"])


class TestLedgerNext(LedgerTestCase):
    def test_returns_first_unblocked_pending_unit(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())

        first = self.tool.ledger_next(str(self.exec_dir))
        self.assertEqual(first["reason"], "ready")
        self.assertEqual(first["unit"]["id"], "stg01")

        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "done", checkpoint="sha")
        second = self.tool.ledger_next(str(self.exec_dir))
        self.assertEqual(second["unit"]["id"], "stg02")

    def test_all_done_returns_null_reason(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        for unit_id in ["stg01", "stg02"]:
            self.tool.ledger_mark(str(self.exec_dir), unit_id, "running")
            self.tool.ledger_mark(str(self.exec_dir), unit_id, "done", checkpoint=unit_id)

        self.assertEqual(self.tool.ledger_next(str(self.exec_dir)), {"unit": None, "reason": "all-done"})


class TestLedgerNextRetry(LedgerTestCase):
    def test_retry_available_for_failed_unit(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="boom")

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertEqual(result["reason"], "retry-available")
        self.assertEqual(result["unit"]["id"], "stg01")

    def test_failed_unit_is_retried_before_other_ready_units(self):
        units = [
            {"stage": "stg01", "title": "A", "depends": [], "group": None, "weight": "green"},
            {"stage": "stg02", "title": "B", "depends": [], "group": None, "weight": "green"},
        ]
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", units)
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="err")

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertEqual(result["reason"], "retry-available")
        self.assertEqual(result["unit"]["id"], "stg01")

    def test_exhausted_unit_not_retried(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        led = self.tool._load(str(self.exec_dir))
        led["units"][0]["status"] = "failed"
        led["units"][0]["attempts"] = 3
        led["units"][0]["last_error"] = "err"
        self.tool._save(str(self.exec_dir), led)

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertEqual((result["reason"], result["unit"]["id"]), ("exhausted", "stg01"))

    def test_stagnated_unit_not_retried(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        led = self.tool._load(str(self.exec_dir))
        led["units"][0]["status"] = "failed"
        led["units"][0]["attempts"] = 1
        led["units"][0]["last_error"] = "Same  error"
        led["units"][0]["previous_error"] = "same error"
        self.tool._save(str(self.exec_dir), led)

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertEqual((result["reason"], result["unit"]["id"]), ("stagnated", "stg01"))


class TestLedgerStatus(LedgerTestCase):
    def test_counts_running_and_exhausted(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        ledger = self.tool._load(str(self.exec_dir))
        ledger["units"][1]["attempts"] = 3
        self.tool._save(str(self.exec_dir), ledger)

        status = self.tool.ledger_status(str(self.exec_dir))

        self.assertEqual(status["counts"], {"pending": 1, "running": 1, "done": 0, "failed": 0})
        self.assertEqual(status["running"], ["stg01"])
        self.assertTrue(status["has_exhausted"])
        self.assertTrue(self.tool.attempts_exhausted({"attempts": 3}))


class TestAtomicSave(LedgerTestCase):
    def test_original_survives_write_failure(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        original = self.tool._load(str(self.exec_dir))

        import unittest.mock as mock
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")

        recovered = self.tool._load(str(self.exec_dir))
        self.assertEqual(recovered, original)


class CheckpointTestCase(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workdir = Path(self.tmp.name) / "repo"
        self.workdir.mkdir()

    def run_git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.workdir,
            capture_output=True,
            text=True,
            check=True,
        )

    def init_repo(self):
        self.run_git("init")
        self.run_git("config", "user.email", "plan-executor@example.test")
        self.run_git("config", "user.name", "Plan Executor Tests")


@unittest.skipUnless(shutil.which("git"), "git required")
class TestCheckpointDetect(CheckpointTestCase):
    def test_detects_git_repo_and_plain_dir(self):
        self.assertEqual(self.tool.checkpoint_detect(str(self.workdir)), {"vcs": "none", "dirty": None})

        self.init_repo()

        self.assertEqual(self.tool.checkpoint_detect(str(self.workdir)), {"vcs": "git", "dirty": False})
        (self.workdir / "new.txt").write_text("x", encoding="utf-8")
        self.assertEqual(self.tool.checkpoint_detect(str(self.workdir)), {"vcs": "git", "dirty": True})


@unittest.skipUnless(shutil.which("git"), "git required")
class TestCheckpointCreate(CheckpointTestCase):
    def test_creates_commit_in_git_repo(self):
        self.init_repo()
        (self.workdir / "file.txt").write_text("one", encoding="utf-8")

        result = self.tool.checkpoint_create(str(self.workdir), "v1")

        self.assertEqual(result["vcs"], "git")
        self.assertRegex(result["checkpoint_id"], r"^[0-9a-f]{40}$")

    def test_create_outside_git_returns_none(self):
        self.assertEqual(self.tool.checkpoint_create(str(self.workdir), "v1"), {"checkpoint_id": None, "vcs": "none", "ref": None})


@unittest.skipUnless(shutil.which("git"), "git required")
class TestCheckpointRestore(CheckpointTestCase):
    def test_restores_to_checkpoint(self):
        self.init_repo()
        target = self.workdir / "file.txt"
        target.write_text("one", encoding="utf-8")
        first = self.tool.checkpoint_create(str(self.workdir), "v1")["checkpoint_id"]
        target.write_text("two", encoding="utf-8")
        self.tool.checkpoint_create(str(self.workdir), "v2")

        result = self.tool.checkpoint_restore(str(self.workdir), first)

        self.assertEqual(result, {"restored_to": first, "removed": []})
        self.assertEqual(target.read_text(encoding="utf-8"), "one")

    def test_restore_outside_git_raises(self):
        with self.assertRaises(ValueError):
            self.tool.checkpoint_restore(str(self.workdir), "abc")


class TestRecommendGate(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_maps_weight_to_gate(self):
        self.assertEqual(self.tool.recommend_gate("red"), {"gate_tier": "red", "no_tests": "escalate"})
        self.assertEqual(self.tool.recommend_gate("unknown"), {"gate_tier": "yellow", "no_tests": "escalate"})


class TestRecommendStrategy(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_base_weight_mapping(self):
        self.assertEqual(self.tool.recommend_strategy("green"), {"isolation": "main", "model_depth": "light", "gate_tier": "green"})
        self.assertEqual(self.tool.recommend_strategy("yellow"), {"isolation": "main", "model_depth": "medium", "gate_tier": "yellow"})
        self.assertEqual(self.tool.recommend_strategy("red"), {"isolation": "subagent", "model_depth": "deep", "gate_tier": "red"})

    def test_keywords_escalate_strategy_but_not_gate(self):
        self.assertEqual(
            self.tool.recommend_strategy("green", "security sensitive migration"),
            {"isolation": "subagent", "model_depth": "deep", "gate_tier": "green"},
        )


class TestScopeContext(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_extracts_en_and_ru_paths_with_dedup(self):
        text = """
## Inputs
- `plan-executor/scripts/executor_tool.py`
- [README.md](./README.md)

## Входные данные
- `plan-executor/scripts/executor_tool.py`
- `plan-executor/assets/ledger.schema.json`

## Other
- `ignored.py`
"""

        self.assertEqual(
            self.tool.scope_context(text),
            {"paths": ["plan-executor/scripts/executor_tool.py", "README.md", "plan-executor/assets/ledger.schema.json"]},
        )

    def test_empty_scope_is_valid(self):
        self.assertEqual(self.tool.scope_context("# Stage\nNo paths"), {"paths": []})


class TestRenderProgress(LedgerTestCase):
    def test_writes_progress_markdown_without_touching_plan(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        before = self.plan_path.read_text(encoding="utf-8")

        result = self.tool.render_progress(str(self.exec_dir))
        progress = Path(result["path"])

        self.assertTrue(progress.is_absolute())
        self.assertEqual(progress.name, "progress.md")
        text = progress.read_text(encoding="utf-8")
        self.assertIn("| Task | Status | Attempts | Weight | Last Error |", text)
        self.assertIn("stg01", text)
        self.assertIn("running", text)
        self.assertEqual(self.plan_path.read_text(encoding="utf-8"), before)


class TestCLI(unittest.TestCase):
    def test_recommend_gate_prints_json(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH), "recommend-gate", "red"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"gate_tier": "red", "no_tests": "escalate"})

    def test_detect_input_prints_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(TOOL_PATH), "detect-input", str(plan)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {"input_type": "whole", "roadmap": None})

    def test_command_exception_prints_json_without_traceback(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH), "parse-roadmap", "missing-roadmap.md"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        data = json.loads(result.stdout)
        self.assertFalse(data["ok"])
        self.assertIn("missing-roadmap.md", data["errors"][0])
        self.assertNotIn("Traceback", result.stderr)

    def test_contract_violation_is_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("## Task 1: A\n", encoding="utf-8")
            exec_dir = str(Path(tmp) / "exec")
            subprocess.run([sys.executable, str(TOOL_PATH), "ledger-init", exec_dir, str(plan)], check=True, capture_output=True)
            result = subprocess.run([sys.executable, str(TOOL_PATH), "ledger-mark", exec_dir, "task-1", "done"],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid transition", json.loads(result.stdout)["errors"][0])

    def test_output_is_utf8_without_pythonioencoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "Plan.md"
            plan.write_text("## Task 1: Проверка — флаг\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
            result = subprocess.run([sys.executable, str(TOOL_PATH), "parse-tasks", str(plan)],
                                    capture_output=True, check=False, env=env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout.decode("utf-8"))["units"][0]["title"], "Проверка — флаг")


class PlanTestCase(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exec_dir = str(self.root / "exec")

    def plan(self, content, name="plan01-impl.md"):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def init(self, plan, **kwargs):
        import types
        defaults = dict(plan_path=plan, exec_dir=self.exec_dir, whole=False, workdir=None, allow_dirty=False, accept_drift=False)
        defaults.update(kwargs)
        return self.tool.cmd_ledger_init(types.SimpleNamespace(**defaults))


class TestWholePlanOrder(PlanTestCase):
    def test_failed_task_blocks_following_tasks(self):
        self.init(self.plan("## Task 1: A\n\n## Task 2: B\n\n## Task 3: C\n"))
        self.tool.ledger_mark(self.exec_dir, "task-1", "running")
        self.tool.ledger_mark(self.exec_dir, "task-1", "failed", error="boom")

        result = self.tool.ledger_next(self.exec_dir)

        self.assertEqual((result["reason"], result["unit"]["id"]), ("retry-available", "task-1"))

    def test_running_unit_is_reported_in_progress(self):
        self.init(self.plan("## Task 1: A\n"))
        self.tool.ledger_mark(self.exec_dir, "task-1", "running")
        self.assertEqual(self.tool.ledger_next(self.exec_dir)["reason"], "in-progress")


class TestHeadingHierarchy(PlanTestCase):
    def test_task_headings_win_over_phase_and_step(self):
        plan = self.plan(
            "# P\n\n## Phase 1: Setup\n\n### Task 1.1: A\n\n#### Step 1: x\n\n"
            "### Task 1.2: B\n\n#### Step 1: y\n\n## Phase 2: Next\n\n### Task 2.1: C\n"
        )
        units = self.tool.parse_tasks(plan)["units"]

        self.assertEqual([u["id"] for u in units], ["task-1.1", "task-1.2", "task-2.1"])
        self.assertEqual([u["parallel_group"] for u in units], ["phase-1", "phase-1", "phase-2"])
        self.assertEqual(units[0]["source"]["line_start"], 5)
        self.assertEqual(units[0]["source"]["line_end"], 8)

    def test_plan_without_task_headings_keeps_legacy_keywords(self):
        units = self.tool.parse_tasks(self.plan("## Step 1: A\n\n## Step 2: B\n"))["units"]
        self.assertEqual([u["id"] for u in units], ["task-1", "task-2"])

    def test_headings_inside_code_fences_are_ignored(self):
        plan = self.plan("## Task 1: A\n\n```markdown\n## Task 9: not a task\n```\n\n## Task 2: Checkpoint — works\n")
        units = self.tool.parse_tasks(plan)["units"]
        self.assertEqual([u["id"] for u in units], ["task-1", "task-2"])
        self.assertEqual(units[1]["title"], "Checkpoint — works")

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.tool.parse_tasks(self.plan("## Task 1: A\n\n## Task 1: B\n"))
        self.assertIn("duplicate-unit-id", str(ctx.exception))

    def test_tier_sets_unit_weight(self):
        units = self.tool.parse_tasks(self.plan("# P\n\n**Tier:** Deep\n\n## Task 1: A\n"))["units"]
        self.assertEqual(units[0]["weight"], "red")


class TestInputErrors(PlanTestCase):
    def test_empty_plan_without_whole_is_an_error(self):
        with self.assertRaises(ValueError) as ctx:
            self.init(self.plan("# Prose only\n\nDo stuff.\n"))
        self.assertIn("no-units", str(ctx.exception))
        self.assertFalse((Path(self.exec_dir) / "state.json").exists())

    def test_unknown_roadmap_dependency_is_an_error(self):
        roadmap = self.plan(
            "| Stage | Title | Depends | Group | Weight |\n|---|---|---|---|---|\n| a | A | z | - | green |\n",
            name="r-roadmap.md",
        )
        with self.assertRaises(ValueError) as ctx:
            self.tool.parse_roadmap(roadmap)
        self.assertIn("a -> z", str(ctx.exception))

    def test_roadmap_ids_normalized_like_splitter(self):
        roadmap = self.plan(
            "| Stage | Title | Depends | Group | Weight |\n|---|---|---|---|---|\n"
            "| A | First | - | A | green |\n| b | Second | A c | B | green |\n| C | Third | - | A | green |\n",
            name="r-roadmap.md",
        )
        rows = self.tool.parse_roadmap(roadmap)
        self.assertEqual([r["stage"] for r in rows], ["a", "b", "c"])
        self.assertEqual(rows[1]["depends"], ["a", "c"])

    def test_old_stg_ids_are_rejected(self):
        roadmap = self.plan(
            "| Stage | Title | Depends | Group | Weight |\n|---|---|---|---|---|\n| stg01 | A | - | - | green |\n",
            name="r-roadmap.md",
        )
        with self.assertRaises(ValueError) as ctx:
            self.tool.parse_roadmap(roadmap)
        self.assertIn("invalid-stage-id", str(ctx.exception))

    def test_detect_lang(self):
        self.assertEqual(self.tool.detect_lang("")["lang"], "en")
        self.assertEqual(self.tool.detect_lang("Plan text only")["lang"], "en")
        self.assertEqual(self.tool.detect_lang("План на русском языке with some code")["lang"], "ru")


class TestStagedDrift(PlanTestCase):
    def test_stage_file_change_is_drift(self):
        table = "| Stage | Title | Depends | Group | Weight |\n|---|---|---|---|---|\n| a | A | - | A | green |\n"
        roadmap = self.plan(table, name="plan01-impl-roadmap.md")
        stage = self.plan("# Stage a\n\n## Tasks\n1. do\n", name="plan01-impl-a.md")
        self.init(roadmap)
        Path(stage).write_text("# Stage a\n\n## Tasks\n1. do more\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            self.init(roadmap)
        self.assertIn("plan-drift", str(ctx.exception))
        led = self.init(roadmap, accept_drift=True)
        self.assertEqual(led["units"][0]["id"], "a")


class TestPlanDrift(PlanTestCase):
    def test_changed_plan_stops_until_accepted(self):
        plan = self.plan("## Task 1: A\n\n## Task 2: B\n")
        self.init(plan)
        self.tool.ledger_mark(self.exec_dir, "task-1", "running")
        self.tool.ledger_mark(self.exec_dir, "task-1", "done")
        Path(plan).write_text("## Task 1: A\n\n## Task 3: C\n", encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            self.init(plan)
        self.assertIn("plan-drift", str(ctx.exception))
        self.assertEqual(ctx.exception.details, {"added": ["task-3"], "removed": ["task-2"]})

        led = self.init(plan, accept_drift=True)
        self.assertEqual([(u["id"], u["status"]) for u in led["units"]], [("task-1", "done"), ("task-3", "pending")])

    def test_v1_ledger_is_migrated(self):
        plan = self.plan("## Task 1: A\n")
        led = self.init(plan)
        for key in ("source_sha256", "run_id", "workdir", "baseline_checkpoint"):
            led.pop(key)
        led["version"] = 1
        self.tool._save(self.exec_dir, led)

        migrated = self.init(plan)

        self.assertEqual(migrated["version"], 2)
        self.assertTrue(migrated["source_sha256"])


class TestExtractFiles(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_bold_files_block_with_line_ranges(self):
        text = "### Task 1: A\n\n**Files:**\n- Modify: `cli.py:4-6`\n- Test: `tests/test_cli.py`\n\n**Preconditions:**\n- `other.py` exists\n"
        self.assertEqual(
            self.tool.extract_files(text),
            [{"path": "cli.py", "action": "modify", "lines": "4-6"}, {"path": "tests/test_cli.py", "action": "test", "lines": None}],
        )


@unittest.skipUnless(shutil.which("git"), "git required")
class TestHiddenRefCheckpoints(CheckpointTestCase):
    def test_snapshot_does_not_touch_branch_history(self):
        self.init_repo()
        (self.workdir / "a.txt").write_text("a", encoding="utf-8")
        self.run_git("add", "a.txt")
        self.run_git("commit", "-m", "base")
        head = self.run_git("rev-parse", "HEAD").stdout.strip()
        (self.workdir / "b.txt").write_text("b", encoding="utf-8")

        result = self.tool.checkpoint_create(str(self.workdir), "task-1", "run1")

        self.assertEqual(self.run_git("rev-parse", "HEAD").stdout.strip(), head)
        self.assertEqual(result["ref"], "refs/plan-executor/run1/task-1")
        self.assertIn("?? b.txt", self.run_git("status", "--porcelain").stdout)
        self.assertEqual(self.tool.checkpoint_prune(str(self.workdir), "run1"), {"pruned": ["refs/plan-executor/run1/task-1"]})

    def test_restore_removes_files_created_after_snapshot(self):
        self.init_repo()
        tracked = self.workdir / "a.txt"
        tracked.write_text("one", encoding="utf-8")
        snap = self.tool.checkpoint_create(str(self.workdir), "baseline", "run1")["checkpoint_id"]
        tracked.write_text("two", encoding="utf-8")
        (self.workdir / "junk.txt").write_text("junk", encoding="utf-8")

        result = self.tool.checkpoint_restore(str(self.workdir), snap)

        self.assertEqual(result["removed"], ["junk.txt"])
        self.assertFalse((self.workdir / "junk.txt").exists())
        self.assertEqual(tracked.read_text(encoding="utf-8"), "one")


@unittest.skipUnless(shutil.which("git"), "git required")
class TestUnitBeginFinish(CheckpointTestCase):
    def setUp(self):
        super().setUp()
        self.init_repo()
        (self.workdir / "cli.py").write_text("print(1)\n", encoding="utf-8")
        self.run_git("add", "cli.py")
        self.run_git("commit", "-m", "base")
        self.exec_dir = str(Path(self.tmp.name) / "exec")
        self.plan_path = Path(self.tmp.name) / "plan01-impl.md"
        self.plan_path.write_text(
            "# P\n\n### Task 1: Flag\n\n**Files:**\n- Modify: `cli.py:1-1`\n\n- [ ] **Step 1: edit**\n\n"
            "### Task 2: Checkpoint — works\n\n- [ ] **Step 1: run**\n",
            encoding="utf-8",
        )

    def ledger_init(self, **kwargs):
        import types
        args = dict(plan_path=str(self.plan_path), exec_dir=self.exec_dir, whole=False,
                    workdir=str(self.workdir), allow_dirty=False, accept_drift=False)
        args.update(kwargs)
        return self.tool.cmd_ledger_init(types.SimpleNamespace(**args))

    def test_full_cycle_pass_and_fail(self):
        led = self.ledger_init()
        self.assertRegex(led["baseline_checkpoint"], r"^[0-9a-f]{40}$")

        begin = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begin["reason"], begin["unit"]["id"], begin["unit"]["status"]), ("ready", "task-1", "running"))
        self.assertIn("**Files:**", begin["text"])
        self.assertNotIn("Task 2", begin["text"])
        self.assertEqual(begin["files"], [{"path": "cli.py", "action": "modify", "lines": "1-1"}])

        (self.workdir / "cli.py").write_text("print(2)\n", encoding="utf-8")
        done = self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.assertEqual(done["status"], "done")
        self.assertRegex(done["checkpoint_id"], r"^[0-9a-f]{40}$")

        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "junk.txt").write_text("x", encoding="utf-8")
        failed = self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="smoke failed")
        self.assertEqual((failed["decision"], failed["restore_to"]), ("retry", done["checkpoint_id"]))
        self.assertEqual(self.run_git("log", "--oneline").stdout.count("\n"), 1)

    def test_dirty_worktree_stops_init(self):
        (self.workdir / "cli.py").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            self.ledger_init()
        self.assertIn("dirty-worktree", str(ctx.exception))
        self.assertEqual(self.ledger_init(allow_dirty=True)["workdir"], str(self.workdir.resolve()))

    def test_exec_dir_inside_workdir_is_rejected(self):
        self.exec_dir = str(self.workdir / ".exec")
        with self.assertRaises(ValueError) as ctx:
            self.ledger_init()
        self.assertIn("exec-dir-inside-workdir", str(ctx.exception))


class TestStrategyKeywords(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_keywords_match_whole_words_only(self):
        self.assertEqual(self.tool.recommend_strategy("green", "Update author list")["model_depth"], "light")
        self.assertEqual(self.tool.recommend_strategy("green", "Add OAuth login")["model_depth"], "deep")


if __name__ == "__main__":
    unittest.main()
