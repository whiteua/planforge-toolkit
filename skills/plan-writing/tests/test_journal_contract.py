"""Cross-skill contract: one chain journal driven by the pipeline skills.

Replays, in a temp dir, the journal calls the skills make for one plan (writing, revision,
split skipped, execution with unit events, diffs, audit open -> audit-open re-entry -> final with
fix_files, commit and a recommit, a drift re-entry only after an answered drift question) and a
silent-mode stop (question -> stopped -> answer -> applied -> running -> done). brainstorm_tool.py is loaded by path, as the skills load it.
Run: python -m pytest skills/plan-writing/tests/test_journal_contract.py -q
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
BRAINSTORM = os.path.abspath(os.path.join(HERE, "..", "..", "plan-brainstorming", "scripts", "brainstorm_tool.py"))

SPEC = "> Tier: Quick\n> Backlog: demo\n\n# Goal\n\nDemo goal.\n"
PLAN = ("# Demo — Implementation Plan\n\n**Spec:** demo-spec.md\n\n**Tier:** Quick\n\n"
        "### Task 1: Demo\n\n- [ ] **Step 1: Run**\n")
STAGES_DONE = {"writing": "done", "revision": "done", "split": "skipped", "execution": "done",
               "diffs": "done", "audit": "done", "commit": "done"}


def _load_brainstorm():
    spec = importlib.util.spec_from_file_location("brainstorm_tool_journal_contract", BRAINSTORM)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*args):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, BRAINSTORM, *args], capture_output=True, encoding="utf-8", env=env)
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else None)


def _write(root, name, text):
    path = os.path.join(root, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@unittest.skipUnless(os.path.isfile(BRAINSTORM), "plan-brainstorming not installed alongside")
class JournalContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bt = _load_brainstorm()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.spec = _write(self.root, "demo-spec.md", SPEC)
        self.plan = _write(self.root, "demo-impl.md", PLAN)
        info = self.bt.journal_path_for(self.spec)
        self.journal = info["journal"]
        self.bt.journal_create(self.journal, info["goal"], "en", self.spec)

    def _event(self, skill, stage, status, **kwargs):
        return self.bt.journal_event(self.journal, skill, self.plan, stage, status, **kwargs)

    def _assert_valid(self):
        result = self.bt.journal_validate(self.journal)
        self.assertTrue(result["ok"], result["errors"])

    def test_full_chain_replays_and_validates(self):
        bt, plan = self.bt, self.plan
        self.assertEqual(os.path.basename(self.journal), "demo-chain.json")
        self._event("plan-writing", "writing", "running", spec=self.spec)
        self._event("plan-writing", "writing", "done", input_path=self.spec, artifacts=["plan=demo-impl.md"])
        self._event("plan-iterative-revision", "revision", "running")
        self._event("plan-iterative-revision", "revision", "done", input_path=plan,
                    artifacts=["review=demo-impl-review-1.md", "completion=demo-impl-completion.md", "verdict=converged"])
        self._event("plan-splitter", "split", "skipped")
        self._event("plan-executor", "execution", "running")
        bt.journal_unit(self.journal, plan, "unit-begin", {"unit": "task-1", "done": 0, "total": 1})
        bt.journal_unit(self.journal, plan, "unit-finish", {"unit": "task-1", "outcome": "done", "done": 1, "total": 1})
        self._event("plan-executor", "execution", "done", input_path=plan)
        self._event("plan-executor", "diffs", "running")
        self._event("plan-executor", "diffs", "done", artifacts=["diffs=demo-diffs.md"])
        found = bt.journal_finding(self.journal, "plan-executor", plan, "src/util.py", "Helper ignores empty input.",
                                   "An empty list raises IndexError.", line=12)
        self.assertEqual((found["id"], found["action"]), ("F1", "recorded"))
        self._event("plan-resolver", "audit", "running")
        self._event("plan-resolver", "audit", "done", input_path=plan,
                    artifacts=["report=demo-impl-report-1.md", "status=open", "issues=1"])
        self._event("plan-resolver", "audit", "running", reason="audit-open")
        update = self._event("plan-resolver", "audit", "running", artifacts=["fix_files[]=src/app.py"])
        self.assertFalse(update["changed"])
        self._event("plan-resolver", "audit", "done", input_path=plan,
                    artifacts=["report=demo-impl-report-2-final.md", "status=final", "issues=0", "fix_files[]=src/app.py"])
        with self.assertRaises(bt.JournalError):
            self._event("plan-resolver", "audit", "running", reason="audit-open", artifacts=["status=open"])
        self._event("plan-executor", "commit", "running")
        rebuilt = self._event("plan-executor", "diffs", "done", artifacts=["diffs=demo-diffs.md"])
        self.assertFalse(rebuilt["changed"])
        self.assertEqual(bt.journal_load(self.journal)["events"][-1]["kind"], "diffs-rebuilt")
        bt.journal_add_commit(self.journal, plan, "a" * 40, "feat(demo): add the demo feature", ["src/app.py", "src/util.py"])
        self._event("plan-executor", "commit", "done")
        self._event("plan-executor", "commit", "running", reason="recommit")
        bt.journal_add_commit(self.journal, plan, "b" * 40, "fix(demo): apply the audit fixes", ["src/app.py"])
        self._event("plan-executor", "commit", "done")
        with self.assertRaises(bt.JournalError):
            self._event("plan-writing", "writing", "running")
        with self.assertRaises(bt.JournalError):
            self._event("plan-writing", "writing", "running", reason="drift")
        drift = bt.journal_question(self.journal, "plan-writing", plan, "writing",
                                    "drift: writing input changed: demo-spec.md", options=["rewrite", "keep"])
        self.assertEqual((drift["id"], drift["stage_status"]), ("Q1", "done"))
        entry = bt.journal_show(self.journal, plan=plan)["plans"][0]
        self.assertEqual((entry["next_action"], entry["owner"], entry["open_questions"]), ("answer", "plan-writing", ["Q1"]))
        bt.journal_answer(self.journal, "Q1", answer="rewrite")
        self._event("plan-writing", "writing", "running", reason="drift")
        self._event("plan-writing", "writing", "done", input_path=self.spec, artifacts=["plan=demo-impl.md"])
        bt.journal_answer(self.journal, "Q1", applied=True)
        exported = bt.journal_export_findings(self.journal)

        self._assert_valid()
        entry = bt.journal_show(self.journal)["plans"][0]
        self.assertEqual((entry["id"], entry["stages"], entry["current"], entry["next_action"]),
                         ("demo-impl", STAGES_DONE, None, "complete"))
        self.assertEqual((entry["progress"]["done"], entry["progress"]["total"]), (1, 1))
        stages = bt.journal_load(self.journal)["plans"][0]["stages"]
        self.assertIn("input_sha256", stages["writing"])
        self.assertEqual(stages["audit"]["artifacts"]["fix_files"], ["src/app.py"])
        self.assertEqual(stages["audit"]["artifacts"]["status"], "final")
        self.assertEqual([c["sha"] for c in stages["commit"]["artifacts"]["commits"]], ["a" * 40, "b" * 40])
        self.assertEqual((os.path.basename(exported["path"]), exported["count"]), ("demo-followups.json", 1))
        with open(exported["path"], encoding="utf-8") as fh:
            findings, errors, _ = bt.load_findings(fh.read())
        self.assertEqual((errors, [f["file"] for f in findings]), ([], ["src/util.py"]))
        code, out = _run("journal-validate", self.journal)
        self.assertEqual(code, 0, out)
        code, out = _run("journal-show", self.journal, "--plan", self.plan)
        self.assertEqual((code, out["plans"][0]["next_action"]), (0, "complete"), out)

    def test_silent_question_stops_and_resumes(self):
        bt = self.bt
        self._event("plan-writing", "writing", "running", spec=self.spec)
        asked = bt.journal_question(self.journal, "plan-writing", self.plan, "writing",
                                    "Which revision preset?", options=["standard", "deep"])
        self.assertEqual((asked["id"], asked["status"], asked["stage_status"]), ("Q1", "open", "stopped"))
        events = bt.journal_load(self.journal)["events"]
        self.assertEqual([e["kind"] for e in events[-2:]], ["stage-end", "question"])
        self.assertEqual((events[-2]["data"]["from"], events[-2]["data"]["to"]), ("running", "stopped"))
        self._assert_valid()
        entry = bt.journal_show(self.journal, plan=self.plan)["plans"][0]
        self.assertEqual((entry["current"], entry["next_action"], entry["open_questions"]), ("writing", "answer", ["Q1"]))
        with self.assertRaises(bt.JournalError):
            self._event("plan-writing", "writing", "running")
        bt.journal_answer(self.journal, "Q1", answer="deep")
        self.assertEqual(bt.journal_show(self.journal, plan=self.plan)["plans"][0]["next_action"], "resume")
        bt.journal_answer(self.journal, "Q1", applied=True)
        self._event("plan-writing", "writing", "running")
        self._event("plan-writing", "writing", "done", input_path=self.spec, artifacts=["plan=demo-impl.md"])

        self._assert_valid()
        entry = bt.journal_show(self.journal, plan=self.plan)["plans"][0]
        self.assertEqual((entry["current"], entry["next_action"]), ("revision", "run"))
        question = bt.journal_load(self.journal)["questions"][0]
        self.assertEqual((question["status"], question["answer"]), ("applied", "deep"))


if __name__ == "__main__":
    unittest.main()
