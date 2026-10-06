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


GOAL_ROADMAP_TEXT = "> Goal: plan01\n> Specs: 1\n> Generated: 2026-10-05T00:00:00Z\n\n# Roadmap: Goal\n"


class TestGoalRoadmap(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.roadmap = self.root / "plan01-roadmap.md"
        self.roadmap.write_text(GOAL_ROADMAP_TEXT, encoding="utf-8")

    def test_plan_next_to_a_goal_roadmap_stays_whole(self):
        plan = self.root / "plan01.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        self.assertEqual(self.tool.detect_input(str(plan)), {"input_type": "whole", "roadmap": None})

    def test_goal_roadmap_as_input_is_refused(self):
        with self.assertRaisesRegex(self.tool.ToolError, "not-a-split-roadmap: this is a goal roadmap; "
                                                         "run /plan-chain-runner "):
            self.tool.detect_input(str(self.roadmap))
        with self.assertRaisesRegex(self.tool.ToolError, "not-a-split-roadmap"):
            self.tool.parse_roadmap(str(self.roadmap))

    def test_ledger_init_on_a_goal_roadmap_is_exit_2(self):
        result = subprocess.run([sys.executable, str(TOOL_PATH), "ledger-init", str(self.root / "exec"),
                                 str(self.roadmap)], capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(json.loads(result.stdout)["errors"][0].startswith("not-a-split-roadmap"))
        self.assertFalse((self.root / "exec").exists())

    def test_goal_roadmap_is_a_chain_file(self):
        self.assertTrue(self.tool._is_chain_file("docs/x-roadmap.md"))
        self.assertTrue(self.tool._is_chain_file("docs/x-impl-roadmap.md"))

    def test_pattern_equals_plan_brainstorming(self):
        module = self.tool._load_brainstorm_tool()
        if module is None:
            self.skipTest("plan-brainstorming not installed alongside")
        self.assertEqual(self.tool._GOAL_ROADMAP_RE.pattern, module.GOAL_ROADMAP_RE.pattern)


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
class TestRunDiff(CheckpointTestCase):
    def test_diff_between_baseline_and_last_unit_snapshot(self):
        import types
        self.init_repo()
        (self.workdir / "plan.md").write_text("## Task 1: A\n\n## Task 2: B\n", encoding="utf-8")
        (self.workdir / "app.py").write_text("x = 1\n", encoding="utf-8")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "init")
        (self.workdir / "dirty.txt").write_text("pre-existing uncommitted work\n", encoding="utf-8")
        exec_dir = str(Path(self.tmp.name) / "exec")
        args = types.SimpleNamespace(plan_path=str(self.workdir / "plan.md"), exec_dir=exec_dir, whole=False,
                                     workdir=str(self.workdir), allow_dirty=True, accept_drift=False, allow_temp=False)
        self.tool.cmd_ledger_init(args)
        with self.assertRaises(ValueError) as ctx:
            self.tool.run_diff(exec_dir)
        self.assertIn("run-diff-unavailable", str(ctx.exception))
        self.tool.unit_begin(exec_dir)
        (self.workdir / "app.py").write_text("x = 2\n", encoding="utf-8")
        (self.workdir / "new.py").write_text("y = 1\n", encoding="utf-8")
        self.tool.unit_finish(exec_dir, "task-1", "pass")
        diff = self.tool.run_diff(exec_dir)
        # Only what the run changed: the pre-existing dirty file is in the baseline already.
        self.assertEqual(sorted(f["path"] for f in diff["files"]), ["app.py", "new.py"])
        self.assertIn("git diff ", diff["command"])
        self.assertIn("2 files changed", diff["stat"])


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
        self.assertEqual(self.tool.recommend_strategy("green"),
                         {"isolation": "main", "model_depth": "light", "gate_tier": "green", "delegable": True})
        self.assertEqual(self.tool.recommend_strategy("yellow"),
                         {"isolation": "main", "model_depth": "medium", "gate_tier": "yellow", "delegable": False})
        self.assertEqual(self.tool.recommend_strategy("red"),
                         {"isolation": "subagent", "model_depth": "deep", "gate_tier": "red", "delegable": False})

    def test_keywords_escalate_strategy_but_not_gate(self):
        self.assertEqual(
            self.tool.recommend_strategy("green", "security sensitive migration"),
            {"isolation": "subagent", "model_depth": "deep", "gate_tier": "green", "delegable": False},
        )

    def test_delegable_only_for_plain_green_units(self):
        rs = self.tool.recommend_strategy
        self.assertTrue(rs("green", "Update the user guide")["delegable"])
        self.assertFalse(rs("green", "Checkpoint — docs build")["delegable"])
        self.assertFalse(rs("green", "Checkpoint — часть a")["delegable"])
        self.assertFalse(rs("green", "Migrate the docs index")["delegable"])
        self.assertFalse(rs("yellow", "Update the user guide")["delegable"])
        self.assertFalse(rs("green", "Update the user guide", external=True)["delegable"])


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


class TestFix02(PlanTestCase):
    PLAN = (
        "# P\n\n**Tier:** Deep\n\n"
        "### Task 1: Code\n\n**Files:**\n- Modify: `src/a.py`\n- Test: `tests/test_a.py`\n\n- [ ] **Step 1:** x\n\n"
        "### Task 2: Tests only\n\n**Files:**\n- Test: `tests/test_b.py`\n\n- [ ] **Step 1:** x\n\n"
        "### Task 3: Docs\n\n**Files:**\n- Modify: `CLAUDE.md:12`\n- Modify: `docs/guide/intro.md`\n\n- [ ] **Step 1:** x\n\n"
        "### Task 4: Checkpoint — smoke\n\n**External:** `dev_db` — smoke test (allowed by the user 2026-09-30)\n\n"
        "- [ ] **Step 1:** run\n\n**Done when:** ok\n"
    )

    def test_weights_lowered_for_checkpoint_docs_and_tests(self):
        units = self.tool.parse_tasks(self.plan(self.PLAN))["units"]
        self.assertEqual([u["weight"] for u in units], ["red", "yellow", "green", "green"])

    def test_unit_begin_reports_external_lines(self):
        self.init(self.plan(self.PLAN))
        for unit_id in ("task-1", "task-2", "task-3"):
            begun = self.tool.unit_begin(self.exec_dir)
            self.assertEqual(begun["external"], [])
            self.tool.unit_finish(self.exec_dir, unit_id, "pass")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["external"], [{"env": "dev_db", "access": None, "kind": None, "consent": None,
                                              "confirmed": False, "source": None}])

    def test_note_is_stored_and_rendered(self):
        self.init(self.plan(self.PLAN))
        self.tool.unit_begin(self.exec_dir)
        done = self.tool.unit_finish(self.exec_dir, "task-1", "pass", note="also fixed  the offset alias\nbypass")
        self.assertEqual(done["unit"]["notes"], ["also fixed the offset alias bypass"])
        progress = Path(done["progress"]).read_text(encoding="utf-8")
        self.assertIn("- task-1: also fixed the offset alias bypass", progress)
        self.assertEqual(self.tool.validate_ledger(self.tool._load(self.exec_dir)), [])

    def test_auto_exec_dir_and_reported_path(self):
        import types
        repo = self.root / "repo"
        repo.mkdir()
        plan = repo / "plan01-impl.md"
        plan.write_text("## Task 1: A\n", encoding="utf-8")
        args = types.SimpleNamespace(plan_path=str(plan), exec_dir="auto", whole=False, workdir=None,
                                     allow_dirty=False, accept_drift=False, allow_temp=False)
        with self.assertRaises(ValueError) as ctx:
            self.tool.cmd_ledger_init(args)
        self.assertIn("exec-dir-auto-needs-workdir", str(ctx.exception))
        self.assertEqual(Path(self.tool.default_exec_dir(str(repo), str(plan))),
                         (self.root / ".exec" / "repo-plan01-impl").resolve())
        led = self.init(self.plan("## Task 1: A\n"))
        self.assertEqual(Path(led["exec_dir"]), Path(self.exec_dir).resolve())

    def test_temp_exec_dir_rejected_for_a_real_workdir(self):
        real_workdir = str(Path(__file__).resolve().parents[1])
        with self.assertRaises(ValueError) as ctx:
            self.tool._check_exec_dir(self.exec_dir, real_workdir)
        self.assertIn("exec-dir-ephemeral", str(ctx.exception))
        self.tool._check_exec_dir(self.exec_dir, real_workdir, allow_temp=True)
        with tempfile.TemporaryDirectory() as other:  # temp workdir (tests, throwaway clones): allowed
            self.tool._check_exec_dir(self.exec_dir, other)


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


class TestSettingsConsent(PlanTestCase):
    SPEC = (
        "> Tier: Deep\n"
        "> Environment: `test_db` (test) — read=run, write=task — \"Тесты на test_db? — Да\" (2026-10-01)\n"
        "> Environment: `prod_db` (prod) — read=run, write=deny — \"Чтение прода на весь прогон? — Да, только чтение\" (2026-10-01)\n"
        "> Environment: `stage_db` (test) — read=task, write=deny — \"Stage только по задаче? — Да\" (2026-10-01)\n\n"
        "# Goal\n\nЦель.\n"
    )
    PLAN = (
        "# P\n\n**Spec:** plan01-spec.md\n\n**Tier:** Deep\n\n"
        "### Task 1: Read prod\n\n" "**External:** `prod_db` (read) — сверка остатков\n\n- [ ] **Step 1:** x\n\n"
        "### Task 2: Migrate\n\n" "**External:** `test_db` (write) — migrate deploy\n\n- [ ] **Step 1:** x\n\n"
        "### Task 3: Legacy\n\n" "**External:** `test_db` — smoke\n\n- [ ] **Step 1:** x\n"
    )

    def write_pair(self):
        return self.plan(self.SPEC, name="plan01-spec.md"), self.plan(self.PLAN)

    def test_brainstorm_tool_is_loaded_by_path(self):
        module = self.tool._load_brainstorm_tool()
        self.assertTrue(callable(getattr(module, "resolve_settings", None)))
        _, plan = self.write_pair()
        settings, warning = self.tool._resolve_settings(plan)
        self.assertIsNone(warning)
        self.assertEqual(settings["from"], "spec")

    def test_missing_brainstorm_tool_gives_warning(self):
        self.tool._load_brainstorm_tool = lambda: None
        settings, warning = self.tool._resolve_settings(self.plan(self.PLAN))
        self.assertIsNone(settings)
        self.assertIn("plan-brainstorming not installed alongside", warning)

    def test_ledger_init_stores_settings_from_spec(self):
        spec, plan = self.write_pair()
        led = self.init(plan)
        self.assertEqual(led["settings"]["from"], "spec")
        self.assertEqual([env["name"] for env in led["settings"]["environments"]], ["test_db", "prod_db", "stage_db"])
        self.assertTrue(os.path.samefile(led["settings_source"]["path"], spec))
        self.assertEqual(led["settings_source"]["sha256"], self.tool._sha256_file(spec))
        self.assertEqual(led["consents"], {})
        self.assertIsInstance(led["warnings"], list)
        self.assertEqual(self.tool._load(self.exec_dir)["settings_source"], led["settings_source"])

    def test_roadmap_input_reads_settings_through_source(self):
        spec, _ = self.write_pair()
        roadmap = self.plan(
            "# R\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n\n"
            "| Stage | Title | Depends | Group | Weight |\n|---|---|---|---|---|\n| a | A | - | A | green |\n",
            name="plan01-impl-roadmap.md")
        led = self.init(roadmap)
        self.assertEqual(led["input_type"], "staged")
        self.assertTrue(os.path.samefile(led["settings_source"]["path"], spec))

    def test_missing_brainstorm_tool_keeps_settings_null(self):
        _, plan = self.write_pair()
        self.tool._load_brainstorm_tool = lambda: None
        led = self.init(plan)
        self.assertEqual((led["settings"], led["settings_source"]), (None, None))
        self.assertTrue(any("plan-brainstorming not installed alongside" in w for w in led["warnings"]))

    def test_resume_clears_run_consents(self):
        _, plan = self.write_pair()
        self.init(plan)
        led = self.tool._load(self.exec_dir)
        led["consents"] = {"test_db": {"write": True}}
        self.tool._save(self.exec_dir, led)
        self.assertEqual(self.init(plan)["consents"], {})
        self.assertEqual(self.tool._load(self.exec_dir)["consents"], {})

    def test_changed_spec_is_settings_drift_until_accepted(self):
        spec, plan = self.write_pair()
        self.init(plan)
        Path(spec).write_text(self.SPEC.replace("read=run, write=task", "read=run, write=run"), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            self.init(plan)
        self.assertIn("settings-drift", str(ctx.exception))
        self.assertEqual(ctx.exception.details["changed_keys"], ["environments"])
        self.assertEqual(self.tool._load(self.exec_dir)["settings"]["environments"][0]["write"], "task")
        led = self.init(plan, accept_drift=True)
        self.assertEqual(led["settings"]["environments"][0]["write"], "run")
        self.assertEqual(self.init(plan)["settings_source"]["sha256"], self.tool._sha256_file(spec))

    def test_unreadable_spec_with_external_units_stops(self):
        plan = self.plan(self.PLAN)  # plan01-spec.md is not written
        with self.assertRaises(ValueError) as ctx:
            self.init(plan)
        self.assertIn("settings-unavailable", str(ctx.exception))
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("settings-source-missing", " ".join(ctx.exception.details["settings_errors"]))
        self.assertFalse((Path(self.exec_dir) / "state.json").exists())

    def test_unreadable_spec_without_external_units_warns(self):
        led = self.init(self.plan("# P\n\n**Spec:** gone-spec.md\n\n**Tier:** Deep\n\n### Task 1: A\n\n- [ ] **Step 1:** x\n"))
        self.assertTrue(any(w.startswith("settings-unavailable") for w in led["warnings"]))
        self.assertEqual(led["units"][0]["id"], "task-1")

    def test_unreadable_spec_on_resume_keeps_settings_and_warns(self):
        spec = self.plan(self.SPEC, name="plan01-spec.md")
        plan = self.plan("# P\n\n**Spec:** plan01-spec.md\n\n**Tier:** Deep\n\n### Task 1: A\n\n- [ ] **Step 1:** x\n")
        first = self.init(plan)
        os.remove(spec)
        led = self.init(plan)
        self.assertTrue(any(w.startswith("settings-unavailable") for w in led["warnings"]))
        self.assertEqual(led["settings_source"], first["settings_source"])
        self.assertEqual(self.tool._load(self.exec_dir)["settings"], first["settings"])

    def test_unit_begin_reports_consent_per_external_line(self):
        _, plan = self.write_pair()
        self.init(plan)
        first = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(first["external"], [{"env": "prod_db", "access": "read", "kind": "prod", "consent": "run",
                                              "confirmed": True, "source": "spec"}])
        self.assertEqual(first["unit"]["external"], first["external"])
        self.assertEqual(self.tool._load(self.exec_dir)["units"][0]["external"], first["external"])
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        second = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(second["external"], [{"env": "test_db", "access": "write", "kind": "test", "consent": "task",
                                               "confirmed": False, "source": None}])
        self.tool.unit_finish(self.exec_dir, "task-2", "pass")
        legacy = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(legacy["external"], [{"env": "test_db", "access": None, "kind": "test", "consent": None,
                                               "confirmed": False, "source": None}])

    def test_settings_with_errors_never_confirm(self):
        led = {"settings": {"ok": False, "environments": [
            {"name": "test_db", "kind": "test", "read": "run", "write": "run"}]}, "consents": {}}
        entries = self.tool._external_entries("**External:** `test_db` (write) — x\n", led)
        self.assertEqual(entries, [{"env": "test_db", "access": "write", "kind": "test", "consent": None,
                                    "confirmed": False, "source": None}])

    def test_prod_write_is_never_confirmed(self):
        led = {"settings": {"ok": True, "environments": [
            {"name": "prod_db", "kind": "prod", "read": "run", "write": "run"}]},
               "consents": {"prod_db": {"write": True}}}
        entries = self.tool._external_entries("**External:** `prod_db` (WRITE) — x\n", led)
        self.assertEqual((entries[0]["confirmed"], entries[0]["source"]), (False, None))
        reads = self.tool._external_entries("**External:** `prod_db` (read) — x\n", led)
        self.assertEqual((reads[0]["confirmed"], reads[0]["source"]), (True, "spec"))

    def test_every_environment_on_one_line_is_an_entry(self):
        led = {"settings": {"ok": True, "environments": [
            {"name": "test_db", "kind": "test", "read": "run", "write": "task"},
            {"name": "prod_db", "kind": "prod", "read": "run", "write": "deny"}]}, "consents": {}}
        entries = self.tool._external_entries(
            "**External:** `test_db` (read), `prod_db` (write) — run `prisma migrate deploy`\n", led)
        self.assertEqual([(e["env"], e["access"], e["confirmed"]) for e in entries],
                         [("test_db", "read", True), ("prod_db", "write", False)])
        for separator in ("; ", " and ", " "):
            line = "**External:** `test_db` (read)%s`prod_db` (write) — x\n" % separator
            self.assertEqual([(e["env"], e["access"]) for e in self.tool._external_entries(line, led)],
                             [("test_db", "read"), ("prod_db", "write")], separator)
        after_dash = self.tool._external_entries("**External:** `test_db` (write) — run `x` on `prod_db`\n", led)
        self.assertEqual([e["env"] for e in after_dash], ["test_db"])

    def consent_cli(self, env, access):
        result = subprocess.run([sys.executable, str(TOOL_PATH), "consent", self.exec_dir, env, access],
                                capture_output=True, check=False)
        return result.returncode, json.loads(result.stdout.decode("utf-8"))

    def test_run_consent_confirms_later_units(self):
        _, plan = self.write_pair()
        self.init(plan)
        code, out = self.consent_cli("test_db", "write")
        self.assertEqual((code, out["consents"]), (0, {"test_db": {"write": True}}))
        self.tool.unit_begin(self.exec_dir)
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        second = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((second["external"][0]["confirmed"], second["external"][0]["source"]), (True, "session"))

    def test_consent_refusals(self):
        _, plan = self.write_pair()
        self.init(plan)
        for env, access, error in (("prod_db", "write", "consent-prod-write"),
                                   ("stage_db", "write", "consent-denied"),
                                   ("nope_db", "read", "consent-unknown-environment")):
            code, out = self.consent_cli(env, access)
            self.assertEqual(code, 1, out)
            self.assertIn(error, out["errors"][0])
        self.assertEqual(self.tool._load(self.exec_dir)["consents"], {})
        code, out = self.consent_cli("prod_db", "read")
        self.assertEqual((code, out["consents"]), (0, {"prod_db": {"read": True}}))

    def test_unit_finish_keeps_every_note(self):
        _, plan = self.write_pair()
        self.init(plan)
        self.tool.unit_begin(self.exec_dir)
        proc = subprocess.run([sys.executable, str(TOOL_PATH), "unit-finish", self.exec_dir, "task-1", "pass",
                               "--note", "External: prod_db (read) confirmed by the engineer for this task",
                               "--note", "agreed: a smaller fixture"], capture_output=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.tool._load(self.exec_dir)["units"][0]["notes"], [
            "External: prod_db (read) confirmed by the engineer for this task", "agreed: a smaller fixture"])

    def test_schema_declares_settings_and_consent_fields(self):
        schema = json.loads((ROOT / "assets" / "ledger.schema.json").read_text(encoding="utf-8"))
        for key in ("settings", "settings_source", "consents"):
            self.assertIn(key, schema["properties"])
        self.assertNotIn("consents", schema["required"])
        self.assertEqual(schema["properties"]["version"]["enum"], [1, 2])
        external = schema["properties"]["units"]["items"]["properties"]["external"]["items"]
        self.assertEqual(sorted(external["required"]), ["access", "confirmed", "consent", "env", "kind", "source"])


class TestExtractFiles(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_bold_files_block_with_line_ranges(self):
        text = "### Task 1: A\n\n**Files:**\n- Modify: `cli.py:4-6`\n- Test: `tests/test_cli.py`\n\n**Preconditions:**\n- `other.py` exists\n"
        self.assertEqual(
            self.tool.extract_files(text),
            [{"path": "cli.py", "action": "modify", "lines": "4-6"}, {"path": "tests/test_cli.py", "action": "test", "lines": None}],
        )

    def test_action_line_takes_its_first_path_only(self):  # spec 1 of plan-refactoring-04
        text = "\n".join([
            "### Task 1: Action lines",
            "",
            "**Files:**",
            "- Modify: `a/cli.py:4-6` (сейчас: `executor_tool.py` / `-roadmap.md` / `parts.json`)",
            "- Create: `<base>-diffs.md` (шаблон, затем `b/real.py`)",
            "- Move: `old/x.py` → `new/x.py` (и `y.py`)",
            "- Test: [test_cli.py](tests/test_cli.py) и `other.py`",
            "- `notes.txt` и `<X>-diffs.md`",
            "",
            "**Preconditions:**",
            "- `other.py` exists",
            "",
        ])
        self.assertEqual(self.tool.extract_files(text), [
            {"path": "a/cli.py", "action": "modify", "lines": "4-6"},
            {"path": "old/x.py", "action": "move", "lines": None},
            {"path": "new/x.py", "action": "move", "lines": None},
            {"path": "test_cli.py", "action": "test", "lines": None},
            {"path": "notes.txt", "action": None, "lines": None},
            {"path": "<X>-diffs.md", "action": None, "lines": None},
        ])


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


@unittest.skipUnless(shutil.which("git"), "git required")
class TestWorktreeTree(CheckpointTestCase):
    def test_tree_matches_snapshot_and_diff_reports_statuses(self):
        self.init_repo()
        (self.workdir / "keep.txt").write_text("1\n", encoding="utf-8")
        (self.workdir / "gone.txt").write_text("1\n", encoding="utf-8")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "base")
        snap = self.tool.checkpoint_create(str(self.workdir), "s1", "run1")["checkpoint_id"]
        before = self.tool._worktree_tree(str(self.workdir))
        self.assertEqual(before, self.tool._commit_tree(str(self.workdir), snap))
        (self.workdir / "keep.txt").write_text("2\n", encoding="utf-8")
        (self.workdir / "gone.txt").unlink()
        (self.workdir / "new.txt").write_text("n\n", encoding="utf-8")
        after = self.tool._worktree_tree(str(self.workdir))
        self.assertEqual(self.tool._tree_diff(str(self.workdir), before, after), [
            {"path": "gone.txt", "status": "deleted"},
            {"path": "keep.txt", "status": "modified"},
            {"path": "new.txt", "status": "added"},
        ])
        self.assertEqual(self.tool._tree_diff(str(self.workdir), after, after), [])
        # The engineer's index is untouched: new.txt is still untracked.
        self.assertIn("?? new.txt", self.run_git("status", "--porcelain").stdout)

    def test_outside_git_is_none(self):
        self.assertIsNone(self.tool._worktree_tree(str(self.workdir)))
        self.assertIsNone(self.tool._commit_tree(str(self.workdir), None))


class TestForeignSchema(unittest.TestCase):
    def test_schema_describes_foreign_fields(self):
        schema = json.loads((ROOT / "assets" / "ledger.schema.json").read_text(encoding="utf-8"))
        props = schema["properties"]
        self.assertEqual(props["expected_tree"]["type"], ["string", "null"])
        event = props["foreign_events"]["items"]
        self.assertEqual(event["properties"]["decision"]["enum"], ["accepted", "restored"])
        self.assertEqual(event["properties"]["paths"]["items"]["properties"]["status"]["enum"],
                         ["added", "modified", "deleted"])


@unittest.skipUnless(shutil.which("git"), "git required")
class TestForeignChanges(CheckpointTestCase):
    PLAN = ("# P\n\n### Task 1: A\n\n**Files:**\n- Modify: `cli.py`\n\n- [ ] **Step 1: edit**\n\n"
            "### Task 2: B\n\n**Files:**\n- Modify: `util.py`\n\n- [ ] **Step 1: edit**\n")

    def setUp(self):
        import types
        super().setUp()
        self.init_repo()
        for name in ("cli.py", "util.py"):
            (self.workdir / name).write_text(f"# {name}\n", encoding="utf-8")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "base")
        self.exec_dir = str(Path(self.tmp.name) / "exec")
        plan = Path(self.tmp.name) / "plan01-impl.md"
        plan.write_text(self.PLAN, encoding="utf-8")
        self.led = self.tool.cmd_ledger_init(types.SimpleNamespace(
            plan_path=str(plan), exec_dir=self.exec_dir, whole=False, workdir=str(self.workdir),
            allow_dirty=False, accept_drift=False))

    def expected_tree(self):
        return self.tool._load(self.exec_dir).get("expected_tree")

    def cli(self, *args):
        proc = subprocess.run([sys.executable, str(TOOL_PATH), *args], capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout)

    def test_ledger_init_and_unit_finish_set_expected_tree(self):
        baseline_tree = self.run_git("rev-parse", self.led["baseline_checkpoint"] + "^{tree}").stdout.strip()
        self.assertEqual(self.expected_tree(), baseline_tree)
        self.assertEqual(self.led["foreign_events"], [])
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "cli.py").write_text("# changed\n", encoding="utf-8")
        done = self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        snap_tree = self.run_git("rev-parse", done["checkpoint_id"] + "^{tree}").stdout.strip()
        self.assertEqual(self.expected_tree(), snap_tree)
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "util.py").write_text("# half done\n", encoding="utf-8")
        self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="boom")
        self.assertEqual(self.expected_tree(), self.tool._worktree_tree(str(self.workdir)))
        self.assertEqual(self.tool.validate_ledger(self.tool._load(self.exec_dir)), [])

    def test_changed_deleted_and_new_files_stop_unit_begin(self):
        (self.workdir / "cli.py").write_text("# edited by hand\n", encoding="utf-8")
        (self.workdir / "util.py").unlink()
        (self.workdir / "notes.txt").write_text("x\n", encoding="utf-8")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["reason"], "foreign-changes")
        self.assertEqual(begun["foreign_changes"], [
            {"path": "cli.py", "status": "modified"},
            {"path": "notes.txt", "status": "added"},
            {"path": "util.py", "status": "deleted"},
        ])
        self.assertEqual(begun["unit"]["id"], "task-1")
        self.assertEqual(begun["expected_tree"], self.expected_tree())
        self.assertEqual(self.tool._load(self.exec_dir)["units"][0]["status"], "pending")

    def test_clean_tree_and_backlog_change_do_not_alarm(self):
        (self.workdir / "BACKLOG.md").write_text("# Backlog\n", encoding="utf-8")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("ready", []))

    def test_in_progress_skips_the_check(self):
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "util.py").write_text("# edited by hand\n", encoding="utf-8")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "in-progress")

    def test_retry_after_fail_has_no_false_alarm(self):
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "cli.py").write_text("# half done\n", encoding="utf-8")
        self.tool.unit_finish(self.exec_dir, "task-1", "fail", error="boom")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("retry-available", []))

    def test_old_ledger_without_expected_tree_starts_after_next_unit(self):
        led = self.tool._load(self.exec_dir)
        del led["expected_tree"]
        self.tool._save(self.exec_dir, led)
        (self.workdir / "cli.py").write_text("# edited before the upgrade\n", encoding="utf-8")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("ready", None))
        self.assertIn("old ledger", begun["foreign_warning"])
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.assertEqual(self.expected_tree(), self.tool._worktree_tree(str(self.workdir)))
        (self.workdir / "util.py").write_text("# foreign\n", encoding="utf-8")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "foreign-changes")

    def test_resume_after_interrupted_unit_has_no_false_alarm(self):
        import types
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "cli.py").write_text("# half done when the session ended\n", encoding="utf-8")
        self.tool.cmd_ledger_init(types.SimpleNamespace(
            plan_path=str(Path(self.tmp.name) / "plan01-impl.md"), exec_dir=self.exec_dir, whole=False,
            workdir=str(self.workdir), allow_dirty=False, accept_drift=False))
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("ready", []))

    def test_accept_changes_records_event_and_clears_the_alarm(self):
        (self.workdir / "cli.py").write_text("# edited by hand\n", encoding="utf-8")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "foreign-changes")
        result = self.tool.accept_changes(self.exec_dir, note="engineer  fixed a typo")
        self.assertEqual(result["accepted"], [{"path": "cli.py", "status": "modified"}])
        events = self.tool._load(self.exec_dir)["foreign_events"]
        self.assertEqual([(e["decision"], e["note"]) for e in events], [("accepted", "engineer fixed a typo")])
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "ready")

    def test_accept_changes_cli_without_changes(self):
        code, out = self.cli("accept-changes", self.exec_dir)
        self.assertEqual((code, out["accepted"], out["event"]), (0, [], None))

    def test_accept_changes_resets_a_missing_expected_tree(self):
        led = self.tool._load(self.exec_dir)
        led["expected_tree"] = "0" * 40  # not in the object store, as after git gc
        self.tool._save(self.exec_dir, led)
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("ready", None))
        self.assertIn("missing from the object store", begun["foreign_warning"])
        result = self.tool.accept_changes(self.exec_dir)
        self.assertEqual((result["accepted"], result["event"]), ([], None))
        self.assertEqual(self.expected_tree(), self.tool._worktree_tree(str(self.workdir)))

    def test_restore_paths_restores_only_listed_files(self):
        snap = self.led["baseline_checkpoint"]
        (self.workdir / "cli.py").write_text("# foreign\n", encoding="utf-8")
        (self.workdir / "util.py").write_text("# keep me\n", encoding="utf-8")
        (self.workdir / "stray.txt").write_text("x\n", encoding="utf-8")
        result = self.tool.checkpoint_restore_paths(str(self.workdir), snap, ["cli.py", "stray.txt"])
        self.assertEqual((result["restored"], result["removed"]), (["cli.py"], ["stray.txt"]))
        self.assertEqual(result["paths"], [{"path": "cli.py", "status": "modified"},
                                           {"path": "stray.txt", "status": "added"}])
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# cli.py\n")
        self.assertFalse((self.workdir / "stray.txt").exists())
        self.assertEqual((self.workdir / "util.py").read_text(encoding="utf-8"), "# keep me\n")

    def test_restore_paths_brings_back_a_deleted_file_from_a_tree(self):
        (self.workdir / "util.py").unlink()
        result = self.tool.checkpoint_restore_paths(str(self.workdir), self.led["expected_tree"], ["./util.py"])
        self.assertEqual(result["paths"], [{"path": "util.py", "status": "deleted"}])
        self.assertEqual((self.workdir / "util.py").read_text(encoding="utf-8"), "# util.py\n")

    def test_unknown_path_is_exit_2_and_nothing_is_restored(self):
        (self.workdir / "cli.py").write_text("# foreign\n", encoding="utf-8")
        code, out = self.cli("checkpoint-restore", str(self.workdir), self.led["baseline_checkpoint"],
                             "--paths", "cli.py", "ghost.txt")
        self.assertEqual(code, 2)
        self.assertIn("ghost.txt", out["errors"][0])
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# foreign\n")

    def test_path_outside_the_repository_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            self.tool.checkpoint_restore_paths(str(self.workdir), self.led["baseline_checkpoint"], ["../exec/state.json"])
        self.assertIn("invalid-path", str(ctx.exception))

    def test_fail_then_restore_with_exec_dir_has_no_false_alarm(self):
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "cli.py").write_text("# broken\n", encoding="utf-8")
        failed = self.tool.unit_finish(self.exec_dir, "task-1", "fail", error="boom")
        code, out = self.cli("checkpoint-restore", str(self.workdir), failed["restore_to"], "--exec-dir", self.exec_dir)
        self.assertEqual(code, 0)
        self.assertEqual(out["expected_tree"], self.tool._worktree_tree(str(self.workdir)))
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# cli.py\n")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("retry-available", []))
        self.assertEqual(self.tool._load(self.exec_dir)["foreign_events"], [])

    def test_restore_foreign_path_records_events_and_keeps_neighbour(self):
        (self.workdir / "cli.py").write_text("# foreign\n", encoding="utf-8")
        (self.workdir / "util.py").write_text("# wanted\n", encoding="utf-8")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["reason"], "foreign-changes")
        code, out = self.cli("checkpoint-restore", str(self.workdir), begun["expected_tree"],
                             "--paths", "cli.py", "--exec-dir", self.exec_dir)
        self.assertEqual((code, out["restored"]), (0, ["cli.py"]))
        self.assertEqual((self.workdir / "util.py").read_text(encoding="utf-8"), "# wanted\n")
        events = self.tool._load(self.exec_dir)["foreign_events"]
        self.assertEqual([(e["decision"], [p["path"] for p in e["paths"]]) for e in events],
                         [("restored", ["cli.py"]), ("accepted", ["util.py"])])
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "ready")

    def test_missing_ledger_fails_before_restoring(self):
        (self.workdir / "cli.py").write_text("# foreign\n", encoding="utf-8")
        code, out = self.cli("checkpoint-restore", str(self.workdir), self.led["baseline_checkpoint"],
                             "--exec-dir", str(Path(self.tmp.name) / "nope"))
        self.assertEqual(code, 2)
        self.assertIn("ledger not found", out["errors"][0])
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# foreign\n")

    def test_full_restore_keeps_backlog(self):
        backlog = "# Backlog\n\n## g\n\n- [ ] x — plan-brainstorming, g-spec.md, 2026-10-01\n"
        (self.workdir / "BACKLOG.md").write_text(backlog, encoding="utf-8")
        self.tool.unit_begin(self.exec_dir)
        (self.workdir / "cli.py").write_text("# broken\n", encoding="utf-8")
        failed = self.tool.unit_finish(self.exec_dir, "task-1", "fail", error="boom")
        code, out = self.cli("checkpoint-restore", str(self.workdir), failed["restore_to"], "--exec-dir", self.exec_dir)
        self.assertEqual(code, 0, out)
        self.assertNotIn("BACKLOG.md", out["removed"])
        self.assertEqual((self.workdir / "BACKLOG.md").read_text(encoding="utf-8"), backlog)
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# cli.py\n")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "retry-available")

    def test_full_restore_keeps_backlog_present_in_the_snapshot(self):
        (self.workdir / "BACKLOG.md").write_text("# Backlog\n", encoding="utf-8")  # not committed
        self.tool.unit_begin(self.exec_dir)
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")  # the task-1 snapshot holds BACKLOG.md
        self.tool.unit_begin(self.exec_dir)
        backlog = "# Backlog\n\n## g\n\n- [ ] y — plan-resolver, g-impl.md, 2026-10-01\n"
        (self.workdir / "BACKLOG.md").write_text(backlog, encoding="utf-8")
        (self.workdir / "cli.py").write_text("# broken\n", encoding="utf-8")
        failed = self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="boom")
        code, out = self.cli("checkpoint-restore", str(self.workdir), failed["restore_to"], "--exec-dir", self.exec_dir)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.workdir / "BACKLOG.md").read_text(encoding="utf-8"), backlog)
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# cli.py\n")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "retry-available")


class TestForeignChangesOutsideGit(CheckpointTestCase):
    def test_outside_git_foreign_changes_is_null(self):
        import types
        (self.workdir / "cli.py").write_text("x\n", encoding="utf-8")
        plan = Path(self.tmp.name) / "plan01-impl.md"
        plan.write_text("# P\n\n### Task 1: A\n\n- [ ] **Step 1: edit**\n", encoding="utf-8")
        exec_dir = str(Path(self.tmp.name) / "exec")
        self.tool.cmd_ledger_init(types.SimpleNamespace(plan_path=str(plan), exec_dir=exec_dir, whole=False,
                                                        workdir=str(self.workdir), allow_dirty=False, accept_drift=False))
        (self.workdir / "cli.py").write_text("y\n", encoding="utf-8")
        begun = self.tool.unit_begin(exec_dir)
        self.assertEqual((begun["reason"], begun["foreign_changes"]), ("ready", None))
        self.assertIn("not a git repository", begun["foreign_warning"])


@unittest.skipUnless(shutil.which("git"), "git required")
class TestBacklogIsNotDirty(CheckpointTestCase):
    BACKLOG = "# Backlog\n\n## g\n\n- [ ] x — plan-executor, g-impl.md, 2026-10-01\n"

    def setUp(self):
        super().setUp()
        self.init_repo()
        (self.workdir / "cli.py").write_text("x = 1\n", encoding="utf-8")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "base")

    def init(self):
        import types
        plan = Path(self.tmp.name) / "plan01-impl.md"
        plan.write_text("# P\n\n### Task 1: A\n\n- [ ] **Step 1: edit**\n", encoding="utf-8")
        return self.tool.cmd_ledger_init(types.SimpleNamespace(
            plan_path=str(plan), exec_dir=str(Path(self.tmp.name) / "exec"), whole=False,
            workdir=str(self.workdir), allow_dirty=False, accept_drift=False))

    def test_new_backlog_is_not_dirty(self):
        (self.workdir / "BACKLOG.md").write_text(self.BACKLOG, encoding="utf-8")
        self.assertFalse(self.tool.checkpoint_detect(str(self.workdir))["dirty"])
        self.assertRegex(self.init()["baseline_checkpoint"], r"^[0-9a-f]{40}$")

    def test_changed_backlog_is_not_dirty(self):
        (self.workdir / "BACKLOG.md").write_text("# Backlog\n", encoding="utf-8")
        self.run_git("add", "BACKLOG.md")
        self.run_git("commit", "-m", "backlog")
        (self.workdir / "BACKLOG.md").write_text(self.BACKLOG, encoding="utf-8")
        self.assertFalse(self.tool.checkpoint_detect(str(self.workdir))["dirty"])
        self.assertRegex(self.init()["baseline_checkpoint"], r"^[0-9a-f]{40}$")

    def test_other_changed_file_is_still_dirty(self):
        (self.workdir / "BACKLOG.md").write_text(self.BACKLOG, encoding="utf-8")
        (self.workdir / "cli.py").write_text("x = 2\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            self.init()
        self.assertIn("dirty-worktree", str(ctx.exception))
        self.assertEqual(ctx.exception.code, 1)


class TestStrategyKeywords(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_keywords_match_whole_words_only(self):
        self.assertEqual(self.tool.recommend_strategy("green", "Update author list")["model_depth"], "light")
        self.assertEqual(self.tool.recommend_strategy("green", "Add OAuth login")["model_depth"], "deep")


@unittest.skipUnless(shutil.which("git"), "git required")
class TestRestorePathsRoot(CheckpointTestCase):
    PLAN = "# P\n\n### Task 1: A\n\n- [ ] **Step 1:** x\n\n### Task 2: B\n\n- [ ] **Step 1:** x\n"

    def setUp(self):
        super().setUp()
        self.init_repo()
        (self.workdir / "sub").mkdir()
        for name in ("cli.py", "util.py", "sub/mod.py"):
            (self.workdir / name).write_text(f"# {name}\n", encoding="utf-8")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "base")
        self.exec_dir = str(Path(self.tmp.name) / "exec")
        self.plan = Path(self.tmp.name) / "plan01-impl.md"
        self.plan.write_text(self.PLAN, encoding="utf-8")

    def init_ledger(self, workdir=None):
        import types
        return self.tool.cmd_ledger_init(types.SimpleNamespace(
            plan_path=str(self.plan), exec_dir=self.exec_dir, whole=False,
            workdir=str(workdir or self.workdir), allow_dirty=False, accept_drift=False))

    def ledger(self):
        return self.tool._load(self.exec_dir)

    def cli(self, *args):
        proc = subprocess.run([sys.executable, str(TOOL_PATH), *args], capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, json.loads(proc.stdout)

    def test_backlog_alone_is_paths_empty(self):
        led = self.init_ledger()
        (self.workdir / "BACKLOG.md").write_text("# Backlog\n", encoding="utf-8")
        code, out = self.cli("checkpoint-restore", str(self.workdir), led["baseline_checkpoint"],
                             "--paths", "BACKLOG.md", "./BACKLOG.md", "--exec-dir", self.exec_dir)
        self.assertEqual(code, 2, out)
        self.assertIn("paths-empty", out["errors"][0])
        self.assertEqual(self.ledger()["expected_tree"], led["expected_tree"])
        self.assertEqual(self.ledger()["foreign_events"], [])
        self.assertTrue((self.workdir / "BACKLOG.md").exists())

    def test_drive_relative_and_pathspec_magic_are_invalid(self):
        for raw in ("C:cli.py", "c:sub/mod.py", ":(glob)*.py", ":/cli.py"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError) as ctx:
                    self.tool._safe_rel_path(raw)
                self.assertIn("invalid-path", str(ctx.exception))
                self.assertEqual(ctx.exception.code, 2)
        led = self.init_ledger()
        code, out = self.cli("checkpoint-restore", str(self.workdir), led["baseline_checkpoint"], "--paths", "C:cli.py")
        self.assertEqual(code, 2, out)
        self.assertIn("invalid-path", out["errors"][0])

    def test_identical_file_is_unchanged_not_modified(self):
        led = self.init_ledger()
        (self.workdir / "cli.py").write_text("# foreign\n", encoding="utf-8")
        result = self.tool.checkpoint_restore_paths(str(self.workdir), led["baseline_checkpoint"], ["util.py", "cli.py"])
        self.assertEqual(result["paths"], [{"path": "cli.py", "status": "modified"},
                                           {"path": "util.py", "status": "unchanged"}])
        self.assertEqual(result["restored"], ["cli.py", "util.py"])
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# cli.py\n")

    def test_subdir_workdir_restores_root_relative_paths(self):
        sub = self.workdir / "sub"
        self.init_ledger(sub)
        (sub / "mod.py").write_text("# by hand\n", encoding="utf-8")
        (self.workdir / "cli.py").write_text("# kept\n", encoding="utf-8")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["foreign_changes"], [{"path": "cli.py", "status": "modified"},
                                                    {"path": "sub/mod.py", "status": "modified"}])
        code, out = self.cli("checkpoint-restore", str(sub), begun["expected_tree"],
                             "--paths", "sub/mod.py", "--exec-dir", self.exec_dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["paths"], [{"path": "sub/mod.py", "status": "modified"}])
        self.assertEqual((sub / "mod.py").read_text(encoding="utf-8"), "# sub/mod.py\n")
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# kept\n")
        events = self.ledger()["foreign_events"]
        self.assertEqual([(e["decision"], [p["path"] for p in e["paths"]]) for e in events],
                         [("restored", ["sub/mod.py"]), ("accepted", ["cli.py"])])
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "ready")

    def test_subdir_workdir_relative_name_is_unknown(self):
        sub = self.workdir / "sub"
        led = self.init_ledger(sub)
        (sub / "mod.py").write_text("# by hand\n", encoding="utf-8")
        code, out = self.cli("checkpoint-restore", str(sub), led["expected_tree"], "--paths", "mod.py")
        self.assertEqual(code, 2, out)
        self.assertIn("unknown-path: mod.py", out["errors"][0])
        self.assertEqual((sub / "mod.py").read_text(encoding="utf-8"), "# by hand\n")

    def test_subdir_workdir_full_restore_covers_the_repository(self):
        sub = self.workdir / "sub"
        led = self.init_ledger(sub)
        (self.workdir / "cli.py").write_text("# failed attempt\n", encoding="utf-8")
        (sub / "mod.py").write_text("# failed attempt\n", encoding="utf-8")
        (self.workdir / "new-root.py").write_text("x = 1\n", encoding="utf-8")
        code, out = self.cli("checkpoint-restore", str(sub), led["baseline_checkpoint"], "--exec-dir", self.exec_dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["removed"], ["new-root.py"])
        self.assertEqual((self.workdir / "cli.py").read_text(encoding="utf-8"), "# cli.py\n")
        self.assertEqual((sub / "mod.py").read_text(encoding="utf-8"), "# sub/mod.py\n")
        self.assertFalse((self.workdir / "new-root.py").exists())
        self.assertEqual(self.ledger()["expected_tree"], led["expected_tree"])
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "ready")

    def test_nested_backlog_is_not_exempt(self):
        led = self.init_ledger()
        (self.workdir / "sub" / "BACKLOG.md").write_text("# not the shared backlog\n", encoding="utf-8")
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["foreign_changes"], [{"path": "sub/BACKLOG.md", "status": "added"}])
        result = self.tool.checkpoint_restore_paths(str(self.workdir), led["expected_tree"], ["sub/BACKLOG.md"])
        self.assertEqual(result["paths"], [{"path": "sub/BACKLOG.md", "status": "added"}])
        self.assertFalse((self.workdir / "sub" / "BACKLOG.md").exists())

    def test_paths_restore_leaves_root_backlog_alone(self):
        led = self.init_ledger()
        backlog = "# Backlog\n\n## g\n\n- [ ] x — plan-executor, g-impl.md, 2026-10-02\n"
        (self.workdir / "BACKLOG.md").write_text(backlog, encoding="utf-8")
        (self.workdir / "cli.py").write_text("# foreign\n", encoding="utf-8")
        code, out = self.cli("checkpoint-restore", str(self.workdir), led["expected_tree"],
                             "--paths", "cli.py", "BACKLOG.md", "--exec-dir", self.exec_dir)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["paths"], [{"path": "cli.py", "status": "modified"}])
        self.assertEqual((self.workdir / "BACKLOG.md").read_text(encoding="utf-8"), backlog)
        events = self.ledger()["foreign_events"]
        self.assertEqual([(e["decision"], [p["path"] for p in e["paths"]]) for e in events],
                         [("restored", ["cli.py"])])
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "ready")


class TestExternalOutsideFences(PlanTestCase):
    FENCED = ("# P\n\n**Spec:** plan01-spec.md\n\n**Tier:** Deep\n\n### Task 1: Fixture\n\n"
              "```markdown\n**External:** `prod_db` (write) — fixture text\n```\n\n"
              "**External:** `test_db` (read) — smoke\n\n- [ ] **Step 1:** x\n")

    def test_external_lines_skip_fenced_code(self):
        self.assertEqual(self.tool._external_lines(self.FENCED), ["`test_db` (read) — smoke"])

    def test_unit_begin_ignores_fenced_external(self):
        self.plan(TestSettingsConsent.SPEC, name="plan01-spec.md")
        self.init(self.plan(self.FENCED))
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual([(e["env"], e["access"]) for e in begun["external"]], [("test_db", "read")])

    def test_fenced_external_does_not_need_settings(self):
        led = self.init(self.plan("# P\n\n**Spec:** gone-spec.md\n\n**Tier:** Deep\n\n### Task 1: A\n\n"
                                  "~~~\n**External:** `prod_db` (write) — fixture\n~~~\n\n- [ ] **Step 1:** x\n"))
        self.assertTrue(any(w.startswith("settings-unavailable") for w in led["warnings"]))
        self.assertEqual(led["units"][0]["id"], "task-1")

    def test_a_shorter_or_other_fence_inside_a_block_does_not_close_it(self):
        after_block = ("### Task 1\n\n````markdown\nexample:\n```\n````\n\n"
                       "**External:** `prod_db` (write) — migrate\n")
        self.assertEqual(self.tool._external_lines(after_block), ["`prod_db` (write) — migrate"])
        inside_block = "~~~\n```\n**External:** `prod_db` (write) — fixture\n```\n~~~\n"
        self.assertEqual(self.tool._external_lines(inside_block), [])


class TestSettingsSpecNotInUtf8(PlanTestCase):
    """F1: the spec's read error reaches ledger-init as an input error (exit 2), not a crash."""

    def test_spec_not_in_utf8_is_an_input_error(self):
        (self.root / "plan01-spec.md").write_bytes("> Tier: Deep\n\n# Goal\n\nЦель.\n".encode("cp1251"))
        plan = self.plan("# P\n\n**Spec:** plan01-spec.md\n\n### Task 1: A\n\n- [ ] **Step 1:** x\n")
        with self.assertRaises(ValueError) as ctx:
            self.init(plan)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("cannot read", str(ctx.exception))
        self.assertFalse((Path(self.exec_dir) / "state.json").exists())


class TestIncompletePlan(PlanTestCase):
    """Spec 3 of plan-refactoring-02: ledger-init refuses a plan plan-writing has not finished."""

    def test_writing_marker_is_refused(self):
        plan = self.plan("# P\n\n### Task 1: A\n\n- [ ] **Step 1:** x\n\n"
                         "> Writing: in progress (spec sha256 0123456789ab)\n")
        with self.assertRaises(ValueError) as ctx:
            self.init(plan)
        self.assertEqual(ctx.exception.code, 1)
        self.assertTrue(str(ctx.exception).startswith("plan-incomplete: "), str(ctx.exception))
        self.assertFalse((Path(self.exec_dir) / "state.json").exists())


class TestSharedTaskParser(PlanTestCase):
    """Contract plans take their units from brainstorm_tool.parse_plan_tasks; others keep the local parse."""

    FIXTURE = ROOT.parent / "plan-writing" / "tests" / "fixtures" / "plan01-impl.md"

    def test_local_parse_matches_on_the_reference_plan(self):
        shared = self.tool.parse_tasks(str(self.FIXTURE))
        self.tool._load_brainstorm_tool = lambda: None
        self.assertEqual(self.tool.parse_tasks(str(self.FIXTURE)), shared)
        self.assertEqual([u["id"] for u in shared["units"]], ["task-1", "task-1.1", "task-2"])

    def test_next_task_heading_ends_a_unit_at_any_level(self):
        plan = self.plan("### Task 1: A\nx\n#### Task 2: B\ny\n")
        units = self.tool.parse_tasks(plan)["units"]
        self.assertEqual([(u["id"], u["source"]["line_start"], u["source"]["line_end"]) for u in units],
                         [("task-1", 1, 2), ("task-2", 3, 4)])
        self.tool._load_brainstorm_tool = lambda: None
        self.assertEqual(self.tool.parse_tasks(plan)["units"][0]["source"]["line_end"], 4)

    def test_malformed_heading_keeps_the_local_parse(self):
        units = self.tool.parse_tasks(self.plan("## Task 1: A\n\n## Task 2 — B\n"))["units"]
        self.assertEqual([u["id"] for u in units], ["task-1", "task-2"])

    def test_module_without_the_parser_keeps_the_local_parse(self):
        import types
        self.tool._load_brainstorm_tool = lambda: types.SimpleNamespace()
        units = self.tool.parse_tasks(self.plan("## Task 1: A\n\n## Task 2: B\n"))["units"]
        self.assertEqual([u["id"] for u in units], ["task-1", "task-2"])


class TestPartField(unittest.TestCase):
    def test_part_is_kept_only_when_given(self):
        tool = load_tool()
        self.assertEqual(tool._full_unit({"id": "task-1", "part": "a"})["part"], "a")
        self.assertNotIn("part", tool._full_unit({"id": "task-1"}))
        schema = json.loads((ROOT / "assets" / "ledger.schema.json").read_text(encoding="utf-8"))
        items = schema["properties"]["units"]["items"]
        self.assertEqual(items["properties"]["part"]["type"], "string")
        self.assertNotIn("part", items["required"])


MASTER = "# P\n\n**Tier:** Deep\n\n### Task 1: First\n\n### Task 1.1: Second\n\n### Task 2: Checkpoint — smoke\n"
PART_A = (
    "# Stage a: A\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n\n## Goal\n\nG\n\n## Inputs\n\nNone.\n\n"
    "## Tasks\n\n1. Task 1: First\n2. Task 1.1: Second\n\n"
    "### Task 1: First\n\n**Files:**\n- Modify: `src/a.py`\n\n- [ ] **Step 1:** x\n\n"
    "### Task 1.1: Second\n\n**Files:**\n- Test: `tests/test_a.py`\n\n- [ ] **Step 1:** y\n\n"
    "## Completion criteria\n\n- [ ] Task 1: done\n\n## Outputs (handoff)\n\n`src/a.py` changed.\n\n## Notes\n\n—\n"
)
PART_B = (
    "# Stage b: B\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n\n## Goal\n\nG\n\n## Inputs\n\nPart a.\n\n"
    "## Tasks\n\n1. Task 2: Checkpoint — smoke\n\n### Task 2: Checkpoint — smoke\n\n- [ ] **Step 1:** run\n\n"
    "**Done when:** ok\n\n## Completion criteria\n\n- [ ] Task 2: ok\n\n## Outputs (handoff)\n\nNothing.\n\n"
    "## Notes\n\n—\n"
)
ROADMAP_AB = (
    "# Roadmap: P\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n\n"
    "| Stage | Title | Depends on | Parallel group | Weight |\n|---|---|---|---|---|\n"
    "| a | A | — | A | 🟡 medium |\n| b | B | a | B | 🟢 light |\n"
)


class TestPartCheckpointLines(unittest.TestCase):
    def test_criteria_and_handoff_until_notes(self):
        tool = load_tool()
        lines = PART_A.splitlines()
        first, last = tool._part_checkpoint_lines(lines, lines.index("### Task 1.1: Second"))
        self.assertEqual((lines[first - 1], lines[last - 1]), ("## Completion criteria", "`src/a.py` changed."))
        self.assertIsNone(tool._part_checkpoint_lines(["# Stage a", "", "## Notes", ""], 0))
        ru = ["### Task 1: x", "", "## Критерии завершения", "", "- [ ] ok", "", "## Примечания", "—"]
        self.assertEqual(tool._part_checkpoint_lines(ru, 1), (3, 5))


class _SplitCase(PlanTestCase):
    def write_split(self, part_a=PART_A, part_b=PART_B):
        self.plan(MASTER)
        self.plan(part_a, name="plan01-impl-a.md")
        self.plan(part_b, name="plan01-impl-b.md")
        roadmap = self.plan(ROADMAP_AB, name="plan01-impl-roadmap.md")
        rows = self.tool.parse_roadmap(roadmap)
        for row in rows:
            row["source"] = self.tool._stage_source(roadmap, row["stage"])
        return roadmap, rows


class TestStagedUnits(_SplitCase):
    def test_tasks_and_checkpoints_in_roadmap_order(self):
        roadmap, rows = self.write_split()
        units, warnings = self.tool._staged_units(roadmap, rows)
        self.assertEqual(warnings, [])
        self.assertEqual([(u["id"], u["depends"], u["part"], u["parallel_group"], u["weight"]) for u in units],
                         [("task-1", [], "a", "A", "red"), ("task-1.1", ["task-1"], "a", "A", "yellow"),
                          ("part-a-done", ["task-1.1"], "a", "A", "green"),
                          ("task-2", ["part-a-done"], "b", "B", "green"),
                          ("part-b-done", ["task-2"], "b", "B", "green")])
        lines = PART_A.splitlines()
        self.assertEqual(units[0]["source"]["line_start"], lines.index("### Task 1: First") + 1)
        self.assertEqual(lines[units[2]["source"]["line_start"] - 1], "## Completion criteria")
        self.assertEqual(units[2]["title"], "Checkpoint — part a")

    def test_part_without_tasks_stays_one_unit(self):
        roadmap, rows = self.write_split(part_a="# Stage a\n\n## Tasks\n1. do\n")
        units, warnings = self.tool._staged_units(roadmap, rows)
        self.assertEqual(warnings, ["part-without-tasks: a"])
        self.assertEqual([u.get("id", u.get("stage")) for u in units], ["a", "task-2", "part-b-done"])
        self.assertEqual(units[1]["depends"], ["a"])

    def test_part_without_tasks_depends_on_the_checkpoint_of_a_part_with_tasks(self):
        roadmap, rows = self.write_split(part_b="# Stage b: B\n\n## Tasks\n1. do\n")
        units, warnings = self.tool._staged_units(roadmap, rows)
        self.assertEqual(warnings, ["part-without-tasks: b"])
        self.assertEqual([u.get("id", u.get("stage")) for u in units],
                         ["task-1", "task-1.1", "part-a-done", "b"])
        self.assertEqual(units[-1]["depends"], ["part-a-done"])
        self.assertEqual(rows[1]["depends"], ["a"])
        self.init(roadmap)
        for unit in ("task-1", "task-1.1", "part-a-done"):
            self.tool.unit_begin(self.exec_dir)
            self.tool.unit_finish(self.exec_dir, unit, "pass")
        nxt = self.tool.ledger_next(self.exec_dir)
        self.assertEqual((nxt["unit"]["id"], nxt["reason"]), ("b", "ready"))

    def test_part_without_criteria_and_duplicate_ids(self):
        roadmap, rows = self.write_split(part_b=PART_B.split("## Completion criteria")[0])
        units, warnings = self.tool._staged_units(roadmap, rows)
        self.assertEqual(warnings, ["part-without-criteria: b"])
        self.assertIsNone(units[-1]["source"])
        self.assertIn("no completion criteria", units[-1]["title"])
        roadmap, rows = self.write_split(part_b=PART_A.replace("Stage a", "Stage b"))
        with self.assertRaises(ValueError) as ctx:
            self.tool._staged_units(roadmap, rows)
        self.assertIn("duplicate-unit-id: task-1", str(ctx.exception))


class TestStagedLedger(_SplitCase):
    def test_ledger_init_runs_the_tasks_of_the_parts(self):
        roadmap, _ = self.write_split()
        led = self.init(roadmap)
        self.assertEqual([u["id"] for u in led["units"]],
                         ["task-1", "task-1.1", "part-a-done", "task-2", "part-b-done"])
        self.assertEqual((led["input_type"], led["units"][0]["part"], led["warnings"]), ("staged", "a", []))
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertTrue(begun["text"].startswith("### Task 1: First"))
        self.assertNotIn("### Task 1.1", begun["text"])
        self.assertEqual([f["path"] for f in begun["files"]], ["src/a.py"])
        self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.tool.unit_begin(self.exec_dir)
        self.tool.unit_finish(self.exec_dir, "task-1.1", "pass")
        check = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(check["unit"]["id"], "part-a-done")
        self.assertTrue(check["text"].startswith("## Completion criteria"))
        self.assertEqual(self.tool.unit_finish(self.exec_dir, "part-a-done", "pass")["unit"]["status"], "done")

    def test_old_ledger_resumes_without_drift(self):
        roadmap, rows = self.write_split()
        self.tool.ledger_init(self.exec_dir, roadmap, "staged", rows,
                              source_sha256=self.tool._staged_sha256(roadmap, rows))
        led = self.init(roadmap)
        self.assertEqual([u["id"] for u in led["units"]], ["a", "b"])
        self.assertEqual(self.tool.validate_ledger(self.tool._load(self.exec_dir)), [])
        self.assertTrue(self.tool.unit_begin(self.exec_dir)["text"].startswith("# Stage a: A"))

    def test_accept_drift_on_an_old_ledger_starts_the_tasks_again(self):
        roadmap, rows = self.write_split()
        self.tool.ledger_init(self.exec_dir, roadmap, "staged", rows,
                              source_sha256=self.tool._staged_sha256(roadmap, rows))
        self.tool.ledger_mark(self.exec_dir, "a", "running")
        self.tool.ledger_mark(self.exec_dir, "a", "done")
        (self.root / "plan01-impl-b.md").write_text(PART_B.replace("run", "run twice"), encoding="utf-8")
        tasks = ["task-1", "task-1.1", "part-a-done", "task-2", "part-b-done"]
        with self.assertRaises(ValueError) as ctx:
            self.init(roadmap)
        self.assertEqual(ctx.exception.details, {"added": tasks, "removed": ["a", "b"]})
        led = self.init(roadmap, accept_drift=True)
        self.assertEqual([(u["id"], u["status"]) for u in led["units"]], [(unit, "pending") for unit in tasks])

    def test_changed_part_is_drift(self):
        roadmap, _ = self.write_split()
        self.init(roadmap)
        (self.root / "plan01-impl-b.md").write_text(PART_B.replace("run", "run twice"), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            self.init(roadmap)
        self.assertIn("plan-drift", str(ctx.exception))


class TestDelegableUnitBegin(PlanTestCase):
    PLAN = ("# P\n\n**Spec:** plan01-spec.md\n\n**Tier:** Quick\n\n"
            "### Task 1: Guide\n\n**Files:**\n- Modify: `docs/guide.md`\n\n- [ ] **Step 1:** x\n\n"
            "### Task 2: Smoke\n\n**Files:**\n- Modify: `docs/notes.md`\n\n"
            "**External:** `test_db` (read) — smoke\n\n- [ ] **Step 1:** x\n\n"
            "### Task 3: Checkpoint — docs\n\n- [ ] **Step 1:** x\n")

    def test_unit_begin_marks_only_plain_green_units(self):
        self.plan(TestSettingsConsent.SPEC, name="plan01-spec.md")
        self.init(self.plan(self.PLAN))
        seen = []
        for unit in ("task-1", "task-2", "task-3"):
            begun = self.tool.unit_begin(self.exec_dir)
            seen.append((begun["unit"]["id"], begun["strategy"]["model_depth"], begun["strategy"]["delegable"]))
            self.tool.unit_finish(self.exec_dir, unit, "pass")
        self.assertEqual(seen, [("task-1", "light", True), ("task-2", "light", False), ("task-3", "light", False)])


class TestLightSetting(PlanTestCase):
    PLAN = "# P\n\n**Spec:** plan01-spec.md\n\n**Tier:** Quick\n\n### Task 1: Guide\n\n- [ ] **Step 1:** x\n"

    def write(self):
        self.plan("> Tier: Quick\n\n# Goal\n\nЦель.\n", name="plan01-spec.md")
        return self.plan(self.PLAN)

    def test_light_is_stored_per_launch(self):
        plan = self.write()
        self.assertEqual(self.init(plan, light="haiku")["settings"]["light"], "haiku")
        self.assertEqual(self.tool._load(self.exec_dir)["settings"]["light"], "haiku")
        self.assertEqual(self.init(plan, light="sonnet")["settings"]["light"], "sonnet")
        self.assertNotIn("light", self.init(plan)["settings"])  # read from the launch, never from the ledger
        self.assertEqual(self.tool.validate_ledger(self.tool._load(self.exec_dir)), [])

    def test_without_a_settings_object_nothing_is_stored(self):
        plan = self.write()
        self.tool._load_brainstorm_tool = lambda: None
        self.assertIsNone(self.init(plan, light="haiku")["settings"])

    def test_cli_light_and_empty_name(self):
        plan = self.write()
        run = lambda *extra: subprocess.run([sys.executable, str(TOOL_PATH), "ledger-init", self.exec_dir, plan, *extra],
                                            capture_output=True, text=True, encoding="utf-8", check=False)
        proc = run("--light", "haiku")
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["settings"]["light"]), (0, "haiku"))
        proc = run("--light", " ")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("light-invalid", json.loads(proc.stdout)["errors"][0])


class TestDelegatedFinish(PlanTestCase):
    PLAN = "# P\n\n**Tier:** Quick\n\n### Task 1: Guide\n\n- [ ] **Step 1:** x\n\n### Task 2: Notes\n\n- [ ] **Step 1:** x\n"

    def test_the_unit_keeps_the_delegated_model(self):
        self.init(self.plan(self.PLAN))
        self.assertNotIn("delegated", self.tool._load(self.exec_dir)["units"][0])
        self.tool.unit_begin(self.exec_dir)
        done = self.tool.unit_finish(self.exec_dir, "task-1", "pass", delegated="haiku")
        self.assertEqual((done["status"], done["unit"]["delegated"]), ("done", "haiku"))
        self.tool.unit_begin(self.exec_dir)
        failed = self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="boom", delegated="haiku")
        self.assertEqual((failed["decision"], failed["unit"]["delegated"]), ("retry", "haiku"))
        self.tool.unit_begin(self.exec_dir)
        self.tool.unit_finish(self.exec_dir, "task-2", "pass")  # the retry in the main agent: no flag
        led = self.tool._load(self.exec_dir)
        self.assertEqual([unit.get("delegated") for unit in led["units"]], ["haiku", "haiku"])
        self.assertEqual(self.tool.validate_ledger(led), [])

    def test_empty_and_missing_model(self):
        self.init(self.plan(self.PLAN))
        self.tool.unit_begin(self.exec_dir)
        with self.assertRaises(ValueError) as ctx:
            self.tool.unit_finish(self.exec_dir, "task-1", "pass", delegated=" ")
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("delegated-invalid", str(ctx.exception))
        proc = subprocess.run([sys.executable, str(TOOL_PATH), "unit-finish", self.exec_dir, "task-1", "pass", "--delegated"],
                              capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--delegated", proc.stderr)


class TestDelegationSchema(unittest.TestCase):
    def test_schema_declares_delegated_and_light(self):
        schema = json.loads((ROOT / "assets" / "ledger.schema.json").read_text(encoding="utf-8"))
        unit = schema["properties"]["units"]["items"]
        self.assertEqual(unit["properties"]["delegated"]["type"], "string")
        self.assertNotIn("delegated", unit["required"])
        self.assertIn("light", schema["properties"]["settings"]["description"])


class TestWrittenFiles(unittest.TestCase):
    """Spec 2 of plan-refactoring-04: the Written files: block that ends a delegated subagent's reply."""

    def setUp(self):
        self.parse = load_tool()._written_files

    def test_the_block_that_ends_the_reply(self):
        reply = ("Done.\r\n\r\nOutput:\r\n5 passed\r\n\r\nWritten files:\r\ndocs\\guide.md  \r\n./docs/new/a.md\r\n"
                 "\r\n/abs/notes/b.md\r\ndocs/guide.md\r\n\r\n")
        self.assertEqual(self.parse(reply), ["docs/guide.md", "docs/new/a.md", "/abs/notes/b.md"])
        self.assertEqual(self.parse("```\nWritten files:\ndocs/guide.md\n```\n\n"), ["docs/guide.md"])
        self.assertEqual(self.parse("All done.\n\nWritten files: none\n\n"), [])

    def test_missing_empty_or_not_last(self):
        for reply in ("Done, docs/guide.md changed.\n", "",
                      "Written files:\ndocs/guide.md\n\nOutput:\n5 passed\n",
                      "Written files:\ndocs/guide.md\n```\n$ pytest\n```\n",
                      "Written files: none\ndocs/guide.md\n",
                      "Written files:\n\n"):
            self.assertIsNone(self.parse(reply), reply)


@unittest.skipUnless(shutil.which("git"), "git required")
class DelegateCase(unittest.TestCase):
    """A repository with docs/guide.md and app.py committed; app.py changed since (the run's earlier work)."""

    def setUp(self):
        self.tool = load_tool()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(os.path.realpath(tmp.name))
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.write("docs/guide.md", "v1\n")
        self.write("app.py", "x = 1\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
        self.write("app.py", "x = 2\n")
        self.root = os.path.realpath(str(self.repo))
        self.snapshot = str(self.base / "delegate-task-1.json")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, capture_output=True, text=True, check=True)

    def write(self, rel, text, root=None):
        path = (root or self.repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def link(self, name, target):
        try:
            os.symlink(str(target), str(self.repo / name), target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")


class TestDelegateHelpers(DelegateCase):
    def test_root_and_no_git(self):
        self.assertEqual(self.tool._delegate_root(str(self.repo / "docs")), self.root)
        with self.assertRaises(ValueError) as ctx:
            self.tool._delegate_root(str(self.base))
        self.assertEqual((ctx.exception.code, str(ctx.exception)[:7]), (1, "no-git:"))

    def test_paths_inside_and_outside_the_root(self):
        other = self.write("x.md", "o\n", self.base / "other").parent
        rel = lambda path: self.tool._delegate_rel(self.root, path)
        self.assertEqual([rel("docs/guide.md"), rel("./docs/../app.py"), rel(str(self.repo / "app.py"))],
                         ["docs/guide.md", "app.py", "app.py"])
        self.assertEqual([rel("../other/x.md"), rel(str(other / "x.md")), rel(".")], [None, None, None])
        self.link("out", other)
        self.assertIsNone(rel("out/x.md"))

    def test_state_lists_each_changed_file_with_its_hash(self):
        (self.repo / "docs" / "guide.md").unlink()
        self.write("docs/new/a.md", "n\n")
        state = self.tool._delegate_state(self.root)
        self.assertEqual(sorted(state), ["app.py", "docs/guide.md", "docs/new/a.md"])
        self.assertEqual((state["app.py"][0], state["docs/guide.md"], state["docs/new/a.md"][0]),
                         (" M", [" D", None], "??"))
        self.assertRegex(state["docs/new/a.md"][1], r"^[0-9a-f]{40,64}$")
        self.assertNotIn("app.py", self.tool._delegate_state(self.root, {"app.py"}))


class TestDelegateSnapshot(DelegateCase):
    def test_snapshot_records_root_and_entries(self):
        out = self.tool.delegate_snapshot(str(self.repo), self.snapshot)
        data = json.loads(Path(self.snapshot).read_text(encoding="utf-8"))
        self.assertEqual((out["ok"], out["root"], out["kind"], out["entries"], out["warnings"]),
                         (True, self.root, "tree", 2, []))
        self.assertEqual((data["version"], data["root"], data["kind"], sorted(data["entries"])),
                         (2, self.root, "tree", ["app.py", "docs/guide.md"]))
        self.assertEqual(self.tool._load_delegate_snapshot(self.snapshot, self.root), ("tree", data["entries"]))

    def test_a_snapshot_inside_the_repository_leaves_itself_out(self):
        inside = self.repo / "delegate.json"
        self.tool.delegate_snapshot(str(self.repo), str(inside))
        self.assertEqual(sorted(json.loads(inside.read_text(encoding="utf-8"))["entries"]), ["app.py", "docs/guide.md"])

    def test_ignored_files_are_in_the_snapshot(self):  # spec 2 of plan-refactoring-04
        self.write(".gitignore", "*.log\n")
        self.write("build.log", "x\n")
        self.tool.delegate_snapshot(str(self.repo), self.snapshot)
        entries = json.loads(Path(self.snapshot).read_text(encoding="utf-8"))["entries"]
        self.assertEqual(sorted(entries), [".gitignore", "app.py", "build.log", "docs/guide.md"])

    def test_without_plan_brainstorming_the_snapshot_is_git_status(self):
        self.tool._load_brainstorm_tool = lambda: None
        out = self.tool.delegate_snapshot(str(self.repo), self.snapshot)
        self.assertEqual((out["kind"], out["entries"], out["warnings"]),
                         ("git-status", 1, ["tree-snapshot-unavailable"]))

    def test_invalid_snapshots(self):
        bad = self.base / "bad.json"
        cases = [(self.base / "missing.json", None), (bad, "{"),
                 (bad, json.dumps({"version": 2, "root": self.root, "entries": {}})),  # no kind
                 (bad, json.dumps({"version": 1, "root": self.root, "kind": "tree", "entries": {}})),
                 (bad, json.dumps({"version": 2, "root": str(self.base), "kind": "tree", "entries": {}}))]
        for path, text in cases:
            if text is not None:
                bad.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                self.tool._load_delegate_snapshot(str(path), self.root)
            self.assertEqual(ctx.exception.code, 2, text)
            self.assertTrue(str(ctx.exception).startswith("snapshot-invalid:"), str(ctx.exception))

    def test_snapshot_without_git_is_no_git(self):
        with self.assertRaises(ValueError) as ctx:
            self.tool.delegate_snapshot(str(self.base), self.snapshot)
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse(os.path.exists(self.snapshot))


class TestDelegateCheck(DelegateCase):
    def setUp(self):
        super().setUp()
        self.tool.delegate_snapshot(str(self.repo), self.snapshot)
        self.reply_path = self.base / "delegate-task-1-reply.md"

    def reply(self, *files, text=None):
        if text is None:
            text = ("Done.\n\nWritten files:\n" + "".join(f"{path}\n" for path in files) if files
                    else "Done.\n\nWritten files: none\n")
        self.reply_path.write_text(text, encoding="utf-8")
        return str(self.reply_path)

    def check(self, *files, text=None):
        return self.tool.delegate_check(str(self.repo), self.snapshot, self.reply(*files, text=text))

    def test_an_honest_unit_passes(self):
        self.write("docs/guide.md", "v2\n")
        self.write("docs/new/a.md", "n\n")
        self.write("docs/g-chain.json", "{}\n")  # another agent of the chain wrote it: not reported
        out = self.check("docs/guide.md", "./docs/new/a.md")
        self.assertEqual((out["verdict"], out["reply_error"], out["outside"], out["unreported"], out["phantom"]),
                         ("pass", None, [], [], []))
        self.assertEqual(out["changed"], ["docs/g-chain.json", "docs/guide.md", "docs/new/a.md"])

    def test_unreported_and_phantom(self):
        self.write("docs/guide.md", "v2\n")
        self.write("notes.txt", "x\n")
        out = self.check("docs/guide.md", "docs/other.md")
        self.assertEqual((out["verdict"], out["unreported"], out["phantom"]), ("fail", ["notes.txt"], ["docs/other.md"]))

    def test_paths_outside_the_repository_fail(self):
        other = self.base / "other"
        far = self.write("x.md", "o\n", other)
        self.write("docs/guide.md", "v2\n")
        out = self.check("docs/guide.md", "../other/x.md", far.as_posix())
        self.assertEqual((out["verdict"], out["outside"]), ("fail", ["../other/x.md", far.as_posix()]))
        self.link("out", other)
        self.assertEqual(self.check("docs/guide.md", "out/x.md")["outside"], ["out/x.md"])

    def test_an_ignored_file_not_named_is_unreported(self):  # spec 2 of plan-refactoring-04
        self.write(".gitignore", "*.log\n")
        self.tool.delegate_snapshot(str(self.repo), self.snapshot)
        self.write("docs/guide.md", "v2\n")
        self.write("build.log", "x\n")
        out = self.check("docs/guide.md")
        self.assertEqual((out["verdict"], out["unreported"], out["warnings"]), ("fail", ["build.log"], []))

    def test_a_snapshot_of_another_kind_is_invalid(self):
        real = self.tool._load_brainstorm_tool
        self.tool._load_brainstorm_tool = lambda: None
        self.tool.delegate_snapshot(str(self.repo), self.snapshot)
        self.tool._load_brainstorm_tool = real
        with self.assertRaises(ValueError) as ctx:
            self.check()
        self.assertEqual((ctx.exception.code, str(ctx.exception)[:17]), (2, "snapshot-invalid:"))

    def test_snapshot_and_reply_in_an_ignored_exec_dir_inside_the_repository(self):
        self.write(".gitignore", ".exec/\n")
        snapshot = self.repo / ".exec" / "delegate-task-1.json"
        snapshot.parent.mkdir()
        self.tool.delegate_snapshot(str(self.repo), str(snapshot))
        self.write("docs/guide.md", "v2\n")
        reply = self.write(".exec/delegate-task-1-reply.md", "Done.\n\nWritten files:\ndocs/guide.md\n")
        out = self.tool.delegate_check(str(self.repo), str(snapshot), str(reply))
        self.assertEqual((out["verdict"], out["unreported"], out["phantom"], out["changed"]),
                         ("pass", [], [], ["docs/guide.md"]))

    def test_none_with_nothing_changed_passes(self):
        out = self.check()
        self.assertEqual((out["verdict"], out["reply_error"], out["changed"]), ("pass", None, []))

    def test_a_reply_without_the_block_or_with_text_after_it_fails(self):
        self.write("docs/guide.md", "v2\n")
        for text in ("Done: docs/guide.md updated.\n", "Written files:\ndocs/guide.md\n\nOutput:\n1 passed\n"):
            out = self.check(text=text)
            self.assertEqual((out["verdict"], out["reply_error"]), ("fail", "written-list-missing"), text)
            self.assertEqual(out["unreported"], ["docs/guide.md"], text)

    def test_crlf_backslashes_and_a_fence_give_no_false_unreported(self):
        self.write("docs/guide.md", "v2\n")
        self.write("docs/new/a.md", "n\n")
        out = self.check(text="Output:\r\n1 passed\r\n```\r\nWritten files:\r\ndocs\\guide.md  \r\n./docs/new/a.md\r\n```\r\n\r\n")
        self.assertEqual((out["verdict"], out["unreported"], out["phantom"]), ("pass", [], []))

    def test_an_unreadable_reply_is_exit_2(self):
        with self.assertRaises(ValueError) as ctx:
            self.tool.delegate_check(str(self.repo), self.snapshot, str(self.base / "missing-reply.md"))
        self.assertEqual((ctx.exception.code, str(ctx.exception)[:17]), (2, "reply-unreadable:"))

    def test_cli_modes_and_exit_codes(self):
        run = lambda *args: subprocess.run([sys.executable, str(TOOL_PATH), "delegate-check", *args],
                                           capture_output=True, text=True, encoding="utf-8", check=False)
        snapshot = str(self.base / "cli.json")
        proc = run(str(self.repo), "--snapshot-out", snapshot)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["entries"]), (0, 2))
        self.write("docs/guide.md", "v2\n")
        proc = run(str(self.repo), "--snapshot", snapshot, "--reply", self.reply("docs/guide.md"))
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["verdict"]), (0, "pass"))
        proc = run(str(self.repo), "--snapshot", snapshot, "--reply", self.reply())
        self.assertEqual(json.loads(proc.stdout)["unreported"], ["docs/guide.md"])
        self.assertEqual(run(str(self.repo), "--snapshot", str(self.base / "nope.json"), "--reply",
                             self.reply()).returncode, 2)
        proc = run(str(self.repo), "--snapshot", snapshot, "--reply", str(self.base / "nope.md"))
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["errors"][0][:17]), (2, "reply-unreadable:"))
        self.assertEqual(run(str(self.base), "--snapshot-out", snapshot).returncode, 1)
        for args in (("--snapshot", snapshot), ("--snapshot-out", snapshot, "--reply", self.reply())):
            proc = run(str(self.repo), *args)
            self.assertEqual((proc.returncode, json.loads(proc.stdout)["errors"][0][:21]), (2, "delegate-check-usage:"))
        proc = run(str(self.repo), "--snapshot", snapshot, "--files", "docs/guide.md")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--files", proc.stderr)


if __name__ == "__main__":
    unittest.main()
