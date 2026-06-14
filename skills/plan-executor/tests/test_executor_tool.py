import importlib.util
import json
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
            roadmap = root / "Plan002-plan-stg00-roadmap.md"
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
            foreign = root / "plan01-stg00-roadmap.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            foreign.write_text("# Roadmap\n", encoding="utf-8")

            result = self.tool.detect_input(str(plan))

        self.assertEqual(result, {"input_type": "whole", "roadmap": None})

    def test_roadmap_path_as_input_is_staged_self(self):
        with tempfile.TemporaryDirectory() as tmp:
            roadmap = Path(tmp) / "plan01-stg00-roadmap.md"
            roadmap.write_text("# Roadmap\n", encoding="utf-8")

            result = self.tool.detect_input(str(roadmap))

        self.assertEqual(result["input_type"], "staged")
        self.assertEqual(Path(result["roadmap"]).name, roadmap.name)

    def test_force_whole_overrides_existing_roadmap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "plan01.md"
            roadmap = root / "plan01-stg00-roadmap.md"
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

        self.assertEqual(
            result,
            {"units": [{"id": "task-1", "title": "First", "weight": "yellow"}, {"id": "task-abc", "title": "Second", "weight": "yellow"}]},
        )

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

    def test_pending_has_priority_over_failed(self):
        units = [
            {"stage": "stg01", "title": "A", "depends": [], "group": None, "weight": "green"},
            {"stage": "stg02", "title": "B", "depends": [], "group": None, "weight": "green"},
        ]
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", units)
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "running")
        self.tool.ledger_mark(str(self.exec_dir), "stg01", "failed", error="err")

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertEqual(result["reason"], "ready")
        self.assertEqual(result["unit"]["id"], "stg02")

    def test_exhausted_unit_not_retried(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        led = self.tool._load(str(self.exec_dir))
        led["units"][0]["status"] = "failed"
        led["units"][0]["attempts"] = 3
        led["units"][0]["last_error"] = "err"
        self.tool._save(str(self.exec_dir), led)

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertNotEqual(result.get("reason"), "retry-available")

    def test_stagnated_unit_not_retried(self):
        self.tool.ledger_init(str(self.exec_dir), str(self.plan_path), "staged", self.units())
        led = self.tool._load(str(self.exec_dir))
        led["units"][0]["status"] = "failed"
        led["units"][0]["attempts"] = 1
        led["units"][0]["last_error"] = "same"
        led["units"][0]["previous_error"] = "same"
        self.tool._save(str(self.exec_dir), led)

        result = self.tool.ledger_next(str(self.exec_dir))

        self.assertNotEqual(result.get("reason"), "retry-available")


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
        self.assertEqual(self.tool.checkpoint_detect(str(self.workdir)), {"vcs": "none"})

        self.init_repo()

        self.assertEqual(self.tool.checkpoint_detect(str(self.workdir)), {"vcs": "git"})


@unittest.skipUnless(shutil.which("git"), "git required")
class TestCheckpointCreate(CheckpointTestCase):
    def test_creates_commit_in_git_repo(self):
        self.init_repo()
        (self.workdir / "file.txt").write_text("one", encoding="utf-8")

        result = self.tool.checkpoint_create(str(self.workdir), "v1")

        self.assertEqual(result["vcs"], "git")
        self.assertRegex(result["checkpoint_id"], r"^[0-9a-f]{40}$")

    def test_create_outside_git_returns_none(self):
        self.assertEqual(self.tool.checkpoint_create(str(self.workdir), "v1"), {"checkpoint_id": None, "vcs": "none"})


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

        self.assertEqual(result, {"restored_to": first})
        self.assertEqual(target.read_text(encoding="utf-8"), "one")

    def test_restore_outside_git_raises(self):
        with self.assertRaises(RuntimeError):
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


class TestRecommendParallel(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_groups_parallel_units_and_filters_singletons(self):
        units = [
            {"id": "a", "parallel_group": "A"},
            {"id": "b", "parallel_group": "A"},
            {"id": "c", "parallel_group": "B"},
            {"id": "d", "parallel_group": None},
        ]

        result = self.tool.recommend_parallel(units)

        self.assertEqual(result["groups"], {"A": ["a", "b"]})
        self.assertIsInstance(result["recommendation"], str)

    def test_no_parallel_groups_returns_null_recommendation(self):
        result = self.tool.recommend_parallel([{"id": "a", "parallel_group": "A"}, {"id": "b", "parallel_group": "B"}])

        self.assertEqual(result, {"groups": {}, "recommendation": None})


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

    def test_command_exception_prints_stderr_without_traceback(self):
        result = subprocess.run(
            [sys.executable, str(TOOL_PATH), "parse-roadmap", "missing-roadmap.md"],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing-roadmap.md", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
