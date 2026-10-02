import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = ROOT / "scripts" / "executor_tool.py"
SPEC = "> Tier: Deep\n\n# Goal\n\nЖурнал цепочки ведётся при выполнении плана.\n"
PLAN = ("# P\n\n**Spec:** plan01-spec.md\n\n**Tier:** Deep\n\n"
        "### Task 1: A\n\n- [ ] **Step 1: edit**\n\n### Task 2: B\n\n- [ ] **Step 1: edit**\n")


def load_tool():
    spec = importlib.util.spec_from_file_location("executor_tool", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class JournalCase(unittest.TestCase):
    """Spec, plan and journal in a temporary folder; the real brainstorm_tool is loaded by path."""

    def setUp(self):
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.exec_dir = str(self.root / "exec")
        (self.root / "plan01-spec.md").write_text(SPEC, encoding="utf-8")
        self.plan = self.root / "plan01-impl.md"
        self.plan.write_text(PLAN, encoding="utf-8")
        self.journal = self.root / "plan01-chain.json"

    def init(self, **kwargs):
        args = dict(plan_path=str(self.plan), exec_dir=self.exec_dir, whole=False, workdir=None,
                    allow_dirty=False, accept_drift=False, allow_temp=False)
        args.update(kwargs)
        return self.tool.cmd_ledger_init(types.SimpleNamespace(**args))

    def data(self):
        return json.loads(self.journal.read_text(encoding="utf-8"))

    def events(self, *kinds):
        return [event for event in self.data()["events"] if event["kind"] in kinds]

    def stage(self, name="execution"):
        return self.data()["plans"][0]["stages"][name]


class TestJournalCall(JournalCase):
    def test_success_is_none_and_the_event_is_written(self):
        module = self.tool._load_brainstorm_tool()
        info = module.journal_path_for(str(self.plan))
        module.journal_create(info["journal"], info["goal"], "ru", info["spec"])
        led = {"journal": {"path": info["journal"], "plan": "plan01-impl"}}
        self.assertIsNone(self.tool._journal_call(led, "journal_event", "plan-executor", str(self.plan),
                                                  "execution", "running"))
        self.assertEqual(self.stage()["status"], "running")

    def test_errors_are_returned_never_raised(self):
        led = {"journal": {"path": str(self.root / "missing-chain.json"), "plan": "plan01-impl"}}
        self.assertIn("journal-missing", self.tool._journal_call(led, "journal_unit", "plan01-impl", "unit-begin", {}))
        self.assertIsNone(self.tool._journal_call({"journal": None}, "journal_unit", "x", "unit-begin", {}))
        self.tool._load_brainstorm_tool = lambda: None
        self.assertIsNone(self.tool._journal_call(led, "journal_unit", "plan01-impl", "unit-begin", {}))


class TestJournalOpen(JournalCase):
    def test_plan_opens_and_creates_the_journal_of_its_spec(self):
        journal, master, error = self.tool._journal_open(str(self.plan))
        self.assertIsNone(error)
        self.assertEqual(Path(journal["path"]).resolve(), self.journal.resolve())
        self.assertEqual((journal["plan"], Path(master).resolve()), ("plan01-impl", self.plan.resolve()))
        self.assertEqual((self.data()["goal"], self.data()["lang"]), ("plan01", "ru"))

    def test_roadmap_opens_the_journal_of_its_master_plan(self):
        roadmap = self.root / "plan01-impl-roadmap.md"
        roadmap.write_text("# R\n\n> Source: [plan01-impl.md](./plan01-impl.md)\n", encoding="utf-8")
        journal, master, _ = self.tool._journal_open(str(roadmap))
        self.assertEqual((journal["plan"], Path(master).resolve()), ("plan01-impl", self.plan.resolve()))

    def test_without_journal_code_alongside(self):
        real = self.tool._load_brainstorm_tool()
        self.tool._load_brainstorm_tool = lambda: types.SimpleNamespace(resolve_settings=real.resolve_settings)
        self.assertEqual(self.tool._journal_open(str(self.plan)), (None, None, None))
        self.tool._load_brainstorm_tool = lambda: None
        self.assertEqual(self.tool._journal_open(str(self.plan)), (None, None, None))
        self.assertFalse(self.journal.exists())

    def test_missing_spec_is_an_error_text(self):
        self.plan.write_text(PLAN.replace("plan01-spec.md", "gone-spec.md"), encoding="utf-8")
        journal, _, error = self.tool._journal_open(str(self.plan))
        self.assertIsNone(journal)
        self.assertIn("journal-source-missing", error)


class TestJournalAttach(JournalCase):
    def test_ledger_init_stores_the_journal(self):
        led = self.init()
        self.assertEqual(Path(led["journal"]["path"]).resolve(), self.journal.resolve())
        self.assertEqual(led["journal"]["plan"], "plan01-impl")
        self.assertNotIn("journal_error", led)
        self.assertEqual(self.tool._load(self.exec_dir)["journal"], led["journal"])

    def test_without_plan_brainstorming_the_journal_is_null(self):
        self.tool._load_brainstorm_tool = lambda: None
        led = self.init()
        self.assertIsNone(led["journal"])
        self.assertNotIn("journal_error", led)
        self.assertFalse(self.journal.exists())

    def test_journal_error_is_reported_and_the_ledger_is_created(self):
        self.plan.write_text(PLAN.replace("plan01-spec.md", "gone-spec.md"), encoding="utf-8")
        led = self.init()
        self.assertIn("journal-source-missing", led["journal_error"])
        self.assertIsNone(led["journal"])
        self.assertEqual(len(self.tool._load(self.exec_dir)["units"]), 2)

    def test_schema_declares_journal(self):
        schema = json.loads((ROOT / "assets" / "ledger.schema.json").read_text(encoding="utf-8"))
        journal = schema["properties"]["journal"]
        self.assertEqual(journal["type"], ["object", "null"])
        self.assertEqual(journal["required"], ["path", "plan"])


class TestExecutionStageOnInit(JournalCase):
    def set_status(self, status):
        data = self.data()
        data["plans"][0]["stages"]["execution"]["status"] = status
        self.journal.write_text(json.dumps(data), encoding="utf-8")

    def test_first_init_starts_the_stage(self):
        self.init()
        self.assertEqual(self.stage()["status"], "running")
        artifacts = self.stage()["artifacts"]
        self.assertEqual(artifacts["exec_dir"], "exec")  # relative to the journal's folder
        self.assertEqual((artifacts["units_done"], artifacts["units_total"]), ("0", "2"))
        starts = self.events("stage-start")
        self.assertEqual([(e["skill"], e["plan"], e["stage"]) for e in starts],
                         [("plan-executor", "plan01-impl", "execution")])

    def test_resume_of_a_running_stage_adds_no_stage_event(self):
        self.init()
        self.init()
        self.assertEqual(len(self.events("stage-start", "stage-end", "stage-update")), 1)

    def test_stopped_and_failed_stages_restart(self):
        self.init()
        for status in ("stopped", "failed"):
            self.set_status(status)
            self.assertNotIn("journal_error", self.init())
            self.assertEqual(self.stage()["status"], "running")

    def test_done_stage_is_left_alone(self):
        self.init()
        self.set_status("done")
        count = len(self.data()["events"])
        self.init()
        self.assertEqual((self.stage()["status"], len(self.data()["events"])), ("done", count))

    def test_corrupt_journal_is_reported_not_raised(self):
        self.init()
        self.journal.write_text("{", encoding="utf-8")
        led = self.init()
        self.assertIn("journal-corrupt", led["journal_error"])
        self.assertEqual(self.journal.read_text(encoding="utf-8"), "{")


class TestUnitBeginEvents(JournalCase):
    def test_unit_begin_records_progress(self):
        self.init()
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertNotIn("journal_error", begun)
        self.assertEqual([e["data"] for e in self.events("unit-begin")], [{"unit": "task-1", "done": 0, "total": 2}])

    def test_all_done_ends_the_stage_once_with_the_plan_hash(self):
        self.init()
        for unit in ("task-1", "task-2"):
            self.tool.unit_begin(self.exec_dir)
            self.tool.unit_finish(self.exec_dir, unit, "pass")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "all-done")
        self.assertEqual(self.stage()["status"], "done")
        self.assertEqual(self.stage()["input_sha256"], self.tool._sha256_file(str(self.plan)))
        count = len(self.data()["events"])
        self.tool.unit_begin(self.exec_dir)  # all-done again: the done stage gets no second event
        self.assertEqual((len(self.events("stage-end")), len(self.data()["events"])), (1, count))

    def test_exhausted_unit_fails_the_stage(self):
        self.init()
        for attempt in range(3):
            self.tool.unit_begin(self.exec_dir)
            self.tool.unit_finish(self.exec_dir, "task-1", "fail", error=f"error {attempt}")
        self.assertEqual(self.tool.unit_begin(self.exec_dir)["reason"], "exhausted")
        self.assertEqual(self.stage()["status"], "failed")

    def test_missing_journal_is_reported_and_the_unit_runs(self):
        self.init()
        self.journal.unlink()
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertIn("journal-missing", begun["journal_error"])
        self.assertEqual((begun["reason"], begun["unit"]["status"]), ("ready", "running"))

    def test_without_plan_brainstorming_unit_begin_is_unchanged(self):
        self.tool._load_brainstorm_tool = lambda: None
        self.init()
        begun = self.tool.unit_begin(self.exec_dir)
        self.assertEqual(begun["reason"], "ready")
        self.assertNotIn("journal_error", begun)


class TestUnitFinishEvents(JournalCase):
    def test_unit_finish_records_outcome_and_progress(self):
        self.init()
        self.tool.unit_begin(self.exec_dir)
        self.assertNotIn("journal_error", self.tool.unit_finish(self.exec_dir, "task-1", "pass"))
        self.tool.unit_begin(self.exec_dir)
        failed = self.tool.unit_finish(self.exec_dir, "task-2", "fail", error="boom")
        self.assertEqual(failed["decision"], "retry")
        self.assertEqual([e["data"] for e in self.events("unit-finish")],
                         [{"unit": "task-1", "outcome": "pass", "done": 1, "total": 2},
                          {"unit": "task-2", "outcome": "fail", "done": 1, "total": 2}])
        artifacts = self.stage()["artifacts"]
        self.assertEqual((self.stage()["status"], artifacts["units_done"], artifacts["units_total"]),
                         ("running", "1", "2"))
        self.assertEqual(len(self.events("stage-update")), 2)

    def test_missing_journal_is_reported_and_the_unit_is_done(self):
        self.init()
        self.tool.unit_begin(self.exec_dir)
        self.journal.unlink()
        done = self.tool.unit_finish(self.exec_dir, "task-1", "pass")
        self.assertEqual(done["status"], "done")
        self.assertIn("journal-missing", done["journal_error"])


if __name__ == "__main__":
    unittest.main()
